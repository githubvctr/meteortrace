"""Streaming file provenance: identity and integrity without full loads.

Files are hashed in fixed-size chunks so that large source images never
need to be loaded into memory in full, and are opened read-only so that
running an audit cannot itself modify a private input.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

_CHUNK_SIZE = 1 << 20  # 1 MiB


def sha256_file(path: Path) -> str:
    """Compute the SHA-256 digest of a file's contents by streaming it.

    Raises
    ------
    FileNotFoundError
        If `path` does not exist or is not a regular file.
    """
    if not path.is_file():
        raise FileNotFoundError(f"No such file: {path.name!r}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class FileRecord:
    """A provenance record for one input file.

    Deliberately excludes absolute paths: `name` is a basename only, safe
    to publish in machine-readable audit output.
    """

    role: str
    name: str
    byte_size: int
    sha256: str
    detected_format: str | None = None

    def to_dict(self) -> dict:
        return {
            "role": self.role,
            "name": self.name,
            "byte_size": self.byte_size,
            "sha256": self.sha256,
            "detected_format": self.detected_format,
        }


def build_file_record(
    path: Path, role: str, detected_format: str | None = None
) -> FileRecord:
    """Build a `FileRecord` for `path`, hashing its contents.

    Raises
    ------
    FileNotFoundError
        If `path` does not exist or is not a regular file.
    """
    if not path.is_file():
        raise FileNotFoundError(f"No such file: {path.name!r}")
    return FileRecord(
        role=role,
        name=path.name,
        byte_size=path.stat().st_size,
        sha256=sha256_file(path),
        detected_format=detected_format,
    )
