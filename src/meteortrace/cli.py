"""Command-line entry point for MeteorTrace's input-auditing tools."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import meteortrace
from meteortrace.audit import run_audit
from meteortrace.image import read_image_metadata
from meteortrace.interactive_selection import (
    SelectionCancelledError,
    collect_selection_via_matplotlib,
)
from meteortrace.outputs import (
    generate_image_overlay_png,
    generate_radiant_geometry_png,
    write_analysis_json,
    write_provenance_json,
    write_report_md,
    write_trajectory_csv,
)
from meteortrace.pipeline import build_report_sections, run_trail_analysis
from meteortrace.pixels import PixelSpace
from meteortrace.provenance import build_file_record
from meteortrace.selection import (
    SELECTION_SCHEMA_VERSION,
    ManualSelectionRecord,
    save_selection,
)
from meteortrace.trajectory import ProvisionalRadiantModel
from meteortrace.uncertainty import DEFAULT_MONTE_CARLO_SEED


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="meteortrace",
        description="Auditable input-provenance and WCS-ingestion tools for "
        "MeteorTrace.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    audit_parser = subparsers.add_parser(
        "audit-inputs",
        help="Audit reference/target image provenance and WCS compatibility.",
    )
    audit_parser.add_argument("--reference-image", required=True, type=Path)
    audit_parser.add_argument("--target-image", required=True, type=Path)
    audit_parser.add_argument("--wcs", required=True, type=Path)
    audit_parser.add_argument(
        "--derived-image",
        action="append",
        default=[],
        type=Path,
        dest="derived_images",
        help="A derived diagnostic image; may be supplied multiple times.",
    )
    audit_parser.add_argument("--output", required=True, type=Path)
    audit_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Allow overwriting an existing --output file.",
    )

    select_parser = subparsers.add_parser(
        "select-trail",
        help="Interactively collect a repeated manual trail-endpoint selection.",
    )
    select_parser.add_argument("--image", required=True, type=Path)
    select_parser.add_argument("--wcs", required=True, type=Path)
    select_parser.add_argument("--repeats", type=int, default=3)
    select_parser.add_argument("--output", required=True, type=Path)
    select_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Allow overwriting an existing --output file.",
    )

    analyze_parser = subparsers.add_parser(
        "analyze-trail",
        help="Map a saved manual selection through the WCS and spherical geometry.",
    )
    analyze_parser.add_argument("--image", required=True, type=Path)
    analyze_parser.add_argument("--wcs", required=True, type=Path)
    analyze_parser.add_argument("--correspondences", required=True, type=Path)
    analyze_parser.add_argument("--selection", required=True, type=Path)
    analyze_parser.add_argument("--radiant-name", required=True)
    analyze_parser.add_argument("--radiant-ra-deg", required=True, type=float)
    analyze_parser.add_argument("--radiant-dec-deg", required=True, type=float)
    analyze_parser.add_argument("--radiant-frame", default="icrs")
    analyze_parser.add_argument("--samples", type=int, default=10000)
    analyze_parser.add_argument("--seed", type=int, default=DEFAULT_MONTE_CARLO_SEED)
    analyze_parser.add_argument("--output-dir", required=True, type=Path)
    analyze_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Allow overwriting an existing analysis.json in --output-dir.",
    )

    return parser


def _run_audit_inputs(args: argparse.Namespace) -> int:
    if args.output.exists() and not args.overwrite:
        print(
            f"Refusing to overwrite existing output {args.output.name!r} "
            "(pass --overwrite to replace it).",
            file=sys.stderr,
        )
        return 2

    try:
        result = run_audit(
            reference_image=args.reference_image,
            target_image=args.target_image,
            wcs_path=args.wcs,
            derived_images=args.derived_images,
        )
    except (FileNotFoundError, ValueError, OSError) as exc:
        print(f"Audit failed: {exc}", file=sys.stderr)
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(f"Wrote audit result to {args.output.name}")
    return 0


def _run_select_trail(args: argparse.Namespace) -> int:
    if args.output.exists() and not args.overwrite:
        print(
            f"Refusing to overwrite existing output {args.output.name!r} "
            "(pass --overwrite to replace it).",
            file=sys.stderr,
        )
        return 2

    try:
        image_record = build_file_record(args.image, role="direct_solver_image")
        wcs_record = build_file_record(args.wcs, role="wcs")
        image_metadata = read_image_metadata(args.image, role="direct_solver_image")
    except (FileNotFoundError, OSError) as exc:
        print(f"select-trail failed: {exc}", file=sys.stderr)
        return 1

    try:
        start_clicks, end_clicks = collect_selection_via_matplotlib(
            args.image, args.repeats
        )
    except SelectionCancelledError as exc:
        print(f"Selection cancelled, nothing written: {exc}", file=sys.stderr)
        return 3

    try:
        record = ManualSelectionRecord(
            schema_version=SELECTION_SCHEMA_VERSION,
            source_image_name=args.image.name,
            source_image_role="direct_solver_image",
            source_image_sha256=image_record.sha256,
            wcs_sha256=wcs_record.sha256,
            image_width=image_metadata.encoded_width,
            image_height=image_metadata.encoded_height,
            pixel_space=PixelSpace.WCS_SOLVED.value,
            observed_direction=(
                "start_to_end: earlier (top) endpoint clicked first, "
                "later (bottom) endpoint clicked second"
            ),
            start_clicks=start_clicks,
            end_clicks=end_clicks,
            selection_method="matplotlib_interactive",
            software_version=meteortrace.__version__,
        )
    except ValueError as exc:
        print(f"Selection invalid, nothing written: {exc}", file=sys.stderr)
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    save_selection(record, args.output)
    print(f"Wrote trail selection to {args.output.name}")
    return 0


def _run_analyze_trail(args: argparse.Namespace) -> int:
    analysis_path = args.output_dir / "analysis.json"
    if analysis_path.exists() and not args.overwrite:
        print(
            f"Refusing to overwrite existing {analysis_path.name!r} in "
            f"{args.output_dir.name!r} (pass --overwrite to replace it).",
            file=sys.stderr,
        )
        return 2

    radiant_model = ProvisionalRadiantModel(
        name=args.radiant_name,
        ra_deg=args.radiant_ra_deg,
        dec_deg=args.radiant_dec_deg,
        frame=args.radiant_frame,
    )
    try:
        result = run_trail_analysis(
            image_path=args.image,
            wcs_path=args.wcs,
            correspondences_path=args.correspondences,
            selection_path=args.selection,
            radiant_model=radiant_model,
            n_samples=args.samples,
            seed=args.seed,
        )
    except (FileNotFoundError, ValueError, OSError) as exc:
        print(f"analyze-trail failed: {exc}", file=sys.stderr)
        return 1

    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_analysis_json(analysis_path, result.analysis)
    write_trajectory_csv(args.output_dir / "trajectory.csv", result.trail_icrs)
    generate_image_overlay_png(
        args.output_dir / "image_overlay.png",
        args.image,
        result.selection,
        result.start_stats,
        result.end_stats,
    )
    generate_radiant_geometry_png(
        args.output_dir / "radiant_geometry.png",
        result.trail_icrs,
        result.radiant_icrs,
        result.mean_result,
    )
    write_report_md(args.output_dir / "report.md", build_report_sections(result))
    write_provenance_json(args.output_dir / "provenance.json", result.provenance)
    print(f"Wrote analysis outputs to {args.output_dir.name}/")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "audit-inputs":
        return _run_audit_inputs(args)
    if args.command == "select-trail":
        return _run_select_trail(args)
    if args.command == "analyze-trail":
        return _run_analyze_trail(args)

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
