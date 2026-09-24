"""Reject damaged extracted PNGs before they enter the asset repository."""

from pathlib import Path
import struct
import zlib


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def validate_png(path: Path) -> None:
    with path.open("rb") as image:
        if image.read(8) != PNG_SIGNATURE:
            raise ValueError(f"Invalid PNG signature: {path}")

        seen_header = False
        seen_data = False
        inflater = zlib.decompressobj()
        while True:
            header = image.read(8)
            if len(header) != 8:
                raise ValueError(f"Truncated PNG chunk header: {path}")
            length, kind = struct.unpack(">I4s", header)
            if not seen_header and (kind != b"IHDR" or length != 13):
                raise ValueError(f"Missing PNG image header: {path}")

            checksum = zlib.crc32(kind)
            remaining = length
            while remaining:
                block = image.read(min(remaining, 65536))
                if not block:
                    raise ValueError(f"Truncated PNG chunk: {path}")
                checksum = zlib.crc32(block, checksum)
                if kind == b"IHDR":
                    if len(block) != 13 or not all(struct.unpack(">II", block[:8])):
                        raise ValueError(f"Invalid PNG dimensions: {path}")
                elif kind == b"IDAT":
                    seen_data = True
                    try:
                        inflater.decompress(block)
                    except zlib.error as exc:
                        raise ValueError(f"Invalid PNG image data: {path}") from exc
                remaining -= len(block)

            stored_crc = image.read(4)
            if len(stored_crc) != 4 or int.from_bytes(stored_crc, "big") != checksum:
                raise ValueError(f"PNG checksum mismatch: {path}")
            seen_header = True
            if kind == b"IEND":
                if length or not seen_data or not inflater.eof or image.read(1):
                    raise ValueError(f"Incomplete PNG image data: {path}")
                return


def validate_changed_pngs(repo_path: Path, changed_files: list[str]) -> int:
    checked = 0
    for relative in changed_files:
        normalized = relative.replace("\\", "/")
        if not normalized.startswith("newseer/assets/") or not normalized.lower().endswith(".png"):
            continue
        file_path = repo_path / relative
        if file_path.is_file():
            validate_png(file_path)
            checked += 1
    print(f"Validated {checked} changed PNG assets before commit.")
    return checked
