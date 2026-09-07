#!/usr/bin/env python3
"""Validate the static web read model before publishing it."""
from __future__ import annotations
import argparse, json, struct
from pathlib import Path

def validate(catalog_path: Path, bin_path: Path) -> None:
    catalog = json.loads(catalog_path.read_text(encoding='utf-8'))
    items = catalog.get('items')
    if catalog.get('schema') != 1 or not isinstance(items, list):
        raise ValueError('unsupported catalog schema')
    if catalog.get('count') != len(items):
        raise ValueError('catalog count mismatch')
    ids = [item.get('id') for item in items]
    if ids != list(range(1, len(items) + 1)):
        raise ValueError('catalog IDs are not contiguous')
    for item in items:
        if len(item.get('hash', '')) != 40 or not item.get('name'):
            raise ValueError(f'invalid catalog item {item.get("id")}')
    data = bin_path.read_bytes()
    if len(data) < 16 or data[:4] != b'AHXP':
        raise ValueError('invalid presets.bin header')
    version, count, strings = struct.unpack_from('<HxxII', data, 4)
    if version != 1 or count != len(items):
        raise ValueError('catalog/BIN count or version mismatch')
    if strings > len(data) - 16:
        raise ValueError('invalid BIN string table')
    print(f'web model valid: {len(items)} catalog items, {len(data)} BIN bytes')

if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('catalog', type=Path); p.add_argument('bin', type=Path)
    a = p.parse_args(); validate(a.catalog, a.bin)
