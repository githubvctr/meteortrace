"""Command-line entry point for MeteorTrace's input-auditing tools."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from meteortrace.audit import run_audit


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


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "audit-inputs":
        return _run_audit_inputs(args)

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
