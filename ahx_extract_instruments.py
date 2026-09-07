#!/usr/bin/env python3
"""Extract instruments from AHX modules as HivelyTracker-compatible .ins files.

The exported files use HivelyTracker's AHX instrument format:

    THXI + 22-byte instrument header + AHX playlist entries + NUL name

Only the Python standard library is required.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


MAGIC = b"THXI"
MAX_FILENAME_LENGTH = 120


class AHXError(ValueError):
    """Raised when an AHX file is malformed or unsupported."""


@dataclass(frozen=True)
class Instrument:
    number: int
    name: str
    ahx_block: bytes
    hively_payload: bytes

    @property
    def playlist_length(self) -> int:
        return self.ahx_block[21]

    @property
    def sha1(self) -> str:
        # Names are metadata; the hash identifies the actual sound definition.
        return hashlib.sha1(self.hively_payload).hexdigest()


@dataclass(frozen=True)
class Module:
    path: Path
    version: int
    position_length: int
    restart: int
    track_length: int
    track_count: int
    instrument_count: int
    subsong_count: int
    track_zero_omitted: bool
    title: str
    instruments: tuple[Instrument, ...]


def read_c_string(data: bytes, offset: int, label: str) -> tuple[str, int]:
    if offset < 0 or offset >= len(data):
        raise AHXError(f"{label} starts outside the file at offset {offset}")
    end = data.find(b"\0", offset)
    if end < 0:
        raise AHXError(f"{label} has no NUL terminator")
    # AHX names are Amiga 8-bit text. Latin-1 preserves every byte losslessly.
    return data[offset:end].decode("latin-1", errors="replace"), end + 1


def read_optional_name(data: bytes, offset: int) -> tuple[str, int]:
    """Read a possibly missing/truncated AHX name without losing the preset."""
    if offset >= len(data):
        return "", len(data)
    end = data.find(b"\0", offset)
    if end < 0:
        # A few old modules in the collection end without all name terminators.
        # HivelyTracker still loads their instrument data, so do the same.
        return data[offset:].decode("latin-1", errors="replace"), len(data)
    return data[offset:end].decode("latin-1", errors="replace"), end + 1


def ahx_to_thxi(ahx_block: bytes) -> bytes:
    """Convert one AHX module instrument block to a THXI payload."""
    if len(ahx_block) < 22:
        raise AHXError("instrument block is shorter than 22 bytes")

    playlist_length = ahx_block[21]
    expected = 22 + playlist_length * 4
    if len(ahx_block) != expected:
        raise AHXError(
            f"instrument block has {len(ahx_block)} bytes, expected {expected}"
        )

    # HivelyTracker's AHX-compatible standalone format has a 4-byte magic
    # before the same 22-byte fields and the same packed 4-byte playlist
    # entries. In other words, the complete AHX instrument block is copied
    # unchanged after the magic. HivelyTracker only maps its internal 12/15
    # command values back to AHX 6/7 when saving; an AHX module already has
    # the correct on-disk values.
    return MAGIC + ahx_block


def parse_ahx(path: Path) -> Module:
    data = path.read_bytes()
    if len(data) < 14:
        raise AHXError("file is shorter than the 14-byte AHX header")
    if data[:3] != b"THX" or data[3] not in (0, 1):
        got = data[:4].decode("latin-1", errors="replace")
        raise AHXError(f"unsupported header {got!r}; expected THX0 or THX1")

    version = data[3]
    position_length = ((data[6] & 0x0F) << 8) | data[7]
    restart = (data[8] << 8) | data[9]
    track_length = data[10]
    track_count = data[11]
    instrument_count = data[12]
    subsong_count = data[13]
    # HivelyTracker's loader and saver use bit 7 as "track 0 omitted". This
    # is easy to misread because older format descriptions phrase it as a
    # saved flag; the on-disk size and HivelyTracker source establish the
    # inverse semantics used by real AHX files.
    track_zero_omitted = bool(data[6] & 0x80)

    if not 1 <= position_length <= 999:
        raise AHXError(f"invalid position-list length {position_length}")
    if not 1 <= track_length <= 64:
        raise AHXError(f"invalid track length {track_length}")
    if instrument_count > 63:
        raise AHXError(f"invalid instrument count {instrument_count}")

    # track_count is the highest logical track number. When track 0 is omitted
    # there are track_count physical tracks (1..track_count); otherwise there
    # are track_count + 1 physical tracks (0..track_count).
    physical_tracks = track_count if track_zero_omitted else track_count + 1
    cursor = 14 + subsong_count * 2 + position_length * 8
    cursor += physical_tracks * track_length * 3
    if cursor > len(data):
        raise AHXError("position/track data extends beyond end of file")

    instruments: list[Instrument] = []
    for number in range(1, instrument_count + 1):
        if cursor + 22 > len(data):
            raise AHXError(f"instrument {number} header extends beyond end of file")
        playlist_length = data[cursor + 21]
        block_size = 22 + playlist_length * 4
        end = cursor + block_size
        if end > len(data):
            raise AHXError(f"instrument {number} playlist extends beyond end of file")
        ahx_block = data[cursor:end]
        instruments.append(
            Instrument(
                number=number,
                name="",
                ahx_block=ahx_block,
                hively_payload=ahx_to_thxi(ahx_block),
            )
        )
        cursor = end

    title, name_cursor = read_c_string(data, cursor, "song title")
    named_instruments: list[Instrument] = []
    for instrument in instruments:
        name, name_cursor = read_optional_name(data, name_cursor)
        named_instruments.append(
            Instrument(
                number=instrument.number,
                name=name,
                ahx_block=instrument.ahx_block,
                hively_payload=instrument.hively_payload,
            )
        )

    return Module(
        path=path,
        version=version,
        position_length=position_length,
        restart=restart,
        track_length=track_length,
        track_count=track_count,
        instrument_count=instrument_count,
        subsong_count=subsong_count,
        track_zero_omitted=track_zero_omitted,
        title=title,
        instruments=tuple(named_instruments),
    )


def safe_name(value: str, fallback: str) -> str:
    value = value.strip() or fallback
    value = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", "_", value)
    value = value.rstrip(" .") or fallback
    if value.upper() in {"CON", "PRN", "AUX", "NUL"}:
        value = f"_{value}"
    if len(value) > MAX_FILENAME_LENGTH:
        value = value[:MAX_FILENAME_LENGTH].rstrip(" .")
    return value


def iter_ahx_files(source: Path) -> Iterable[Path]:
    if source.is_file():
        if source.suffix.lower() == ".ahx":
            yield source
        return
    yield from sorted(
        (p for p in source.rglob("*") if p.is_file() and p.suffix.lower() == ".ahx"),
        key=lambda p: str(p).casefold(),
    )


def write_ins(path: Path, payload: bytes, name: str) -> None:
    # HivelyTracker stores the instrument name as a single NUL-terminated
    # 8-bit string after the binary payload.
    encoded_name = name.encode("latin-1", errors="replace")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload + encoded_name + b"\0")


def relative_module_path(source: Path, module_path: Path) -> Path:
    if source.is_file():
        return Path(module_path.stem)
    return module_path.relative_to(source).with_suffix("")


def extract(source: Path, output: Path) -> dict[str, int]:
    output.mkdir(parents=True, exist_ok=True)
    by_module = output / "by_module"
    library = output / "library"
    index_path = output / "index.csv"
    summary_path = output / "summary.json"

    rows: list[dict[str, object]] = []
    errors: list[dict[str, str]] = []
    library_paths: dict[str, Path] = {}
    module_count = 0
    instrument_count = 0

    for module_path in iter_ahx_files(source):
        try:
            module = parse_ahx(module_path)
        except (OSError, AHXError) as exc:
            errors.append({"file": str(module_path), "error": str(exc)})
            continue

        module_count += 1
        module_rel = relative_module_path(source, module_path)
        module_folder = by_module / module_rel
        for instrument in module.instruments:
            instrument_count += 1
            fallback = f"{module_path.stem} instrument {instrument.number:02d}"
            display_name = instrument.name or fallback
            filename = f"{instrument.number:02d} - {safe_name(display_name, fallback)}.ins"
            module_output = module_folder / filename
            write_ins(module_output, instrument.hively_payload, display_name)

            digest = instrument.sha1
            if digest not in library_paths:
                library_name = safe_name(display_name, fallback)
                # Put the useful instrument/sample name first in file dialogs;
                # keep the content hash at the end as the stable identifier.
                library_output = library / f"{library_name} - {digest[:12]}.ins"
                write_ins(library_output, instrument.hively_payload, display_name)
                library_paths[digest] = library_output
                duplicate_of = ""
            else:
                duplicate_of = str(library_paths[digest])

            rows.append(
                {
                    "module": str(module_path),
                    "module_title": module.title,
                    "module_version": module.version,
                    "instrument_number": instrument.number,
                    "instrument_name": instrument.name,
                    "fallback_name": fallback,
                    "playlist_length": instrument.playlist_length,
                    "sha1": digest,
                    "module_preset": str(module_output),
                    "library_preset": str(library_paths[digest]),
                    "duplicate_of": duplicate_of,
                }
            )

    with index_path.open("w", newline="", encoding="utf-8-sig") as handle:
        fieldnames = [
            "module",
            "module_title",
            "module_version",
            "instrument_number",
            "instrument_name",
            "fallback_name",
            "playlist_length",
            "sha1",
            "module_preset",
            "library_preset",
            "duplicate_of",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    summary = {
        "source": str(source),
        "output": str(output),
        "modules_found": module_count + len(errors),
        "modules_exported": module_count,
        "modules_failed": len(errors),
        "instrument_occurrences": instrument_count,
        "unique_instruments": len(library_paths),
        "duplicates": instrument_count - len(library_paths),
        "errors": errors,
        "format": "HivelyTracker THXI instrument (.ins)",
    }
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if errors:
        (output / "errors.json").write_text(
            json.dumps(errors, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    else:
        stale_errors = output / "errors.json"
        if stale_errors.exists():
            stale_errors.unlink()
    return {
        "modules": module_count,
        "instruments": instrument_count,
        "unique": len(library_paths),
        "errors": len(errors),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Extract AHX instruments into HivelyTracker-compatible .ins presets."
    )
    parser.add_argument("source", type=Path, help="AHX file or directory to scan recursively")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("ahx_instruments"),
        help="output directory (default: ./ahx_instruments)",
    )
    args = parser.parse_args(argv)

    if not args.source.exists():
        parser.error(f"source does not exist: {args.source}")

    try:
        result = extract(args.source, args.output)
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(
        f"Exported {result['instruments']} instruments from {result['modules']} modules; "
        f"{result['unique']} unique presets; {result['errors']} failed modules."
    )
    if result["errors"]:
        print(f"See {args.output / 'errors.json'} for parse errors.", file=sys.stderr)
    return 1 if result["modules"] == 0 and result["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
