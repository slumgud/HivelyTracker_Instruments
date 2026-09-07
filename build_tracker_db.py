#!/usr/bin/env python3
"""Build SlumTracker's SQLite-independent preset bundle."""
from __future__ import annotations
import argparse
from pathlib import Path
import ahx_database

def main() -> int:
    p = argparse.ArgumentParser(description='Build and validate presets.bin from SQLite')
    p.add_argument('database', type=Path)
    p.add_argument('-o', '--output', type=Path, default=Path('presets.bin'))
    args = p.parse_args()
    ahx_database.export_bin(args.database, args.output)
    ahx_database.validate_bin(args.output)
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
