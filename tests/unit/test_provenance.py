"""Unit tests for `meteortrace.provenance`."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from meteortrace.provenance import build_file_record, sha256_file


def test_sha256_matches_known_fixture(tmp_path: Path) -> None:
    fixture = tmp_path / "fixture.bin"
    payload = b"MeteorTrace deterministic fixture payload."
    fixture.write_bytes(payload)

    expected = hashlib.sha256(payload).hexdigest()
    assert sha256_file(fixture) == expected


def test_sha256_is_deterministic_across_chunk_boundaries(tmp_path: Path) -> None:
    fixture = tmp_path / "large.bin"
    payload = bytes(range(256)) * 10_000  # larger than the internal chunk size
    fixture.write_bytes(payload)

    assert sha256_file(fixture) == hashlib.sha256(payload).hexdigest()


def test_missing_file_raises_explicitly(tmp_path: Path) -> None:
    missing = tmp_path / "does_not_exist.bin"
    with pytest.raises(FileNotFoundError):
        sha256_file(missing)
    with pytest.raises(FileNotFoundError):
        build_file_record(missing, role="reference")


def test_directory_path_raises_explicitly(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        sha256_file(tmp_path)


def test_file_record_has_no_absolute_path_leakage(tmp_path: Path) -> None:
    nested = tmp_path / "nested" / "dir"
    nested.mkdir(parents=True)
    fixture = nested / "example.bin"
    fixture.write_bytes(b"payload")

    record = build_file_record(fixture, role="reference", detected_format="BIN")
    serialized = record.to_dict()

    assert serialized["name"] == "example.bin"
    assert str(tmp_path) not in serialized["name"]
    assert "/" not in serialized["name"]
    assert serialized["role"] == "reference"
    assert serialized["byte_size"] == 7
    assert serialized["detected_format"] == "BIN"
    assert len(serialized["sha256"]) == 64
