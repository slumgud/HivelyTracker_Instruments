#!/usr/bin/env python3
"""Export the SQLite catalog into the static web frontend's read model."""
from __future__ import annotations
import json, sqlite3
from pathlib import Path

def build(db_path: Path, output: Path) -> None:
    db = sqlite3.connect(db_path)
    rows = db.execute('''SELECT i.id,i.name,i.hash_sha1,i.instrument_type,i.metadata_status,
        i.curator_note,COUNT(DISTINCT s.id),GROUP_CONCAT(DISTINCT s.module_title),
        GROUP_CONCAT(DISTINCT s.artist_handle),GROUP_CONCAT(DISTINCT s.artist_group),
        GROUP_CONCAT(DISTINCT t.name),GROUP_CONCAT(DISTINCT s.credits),GROUP_CONCAT(DISTINCT s.source_url)
        FROM instrument i LEFT JOIN instrument_source x ON x.instrument_id=i.id
        LEFT JOIN source s ON s.id=x.source_id LEFT JOIN instrument_tag it ON it.instrument_id=i.id
        LEFT JOIN tag t ON t.id=it.tag_id GROUP BY i.id ORDER BY i.id''').fetchall()
    items = []
    for row in rows:
        items.append({'id': row[0], 'name': row[1], 'hash': row[2], 'type': row[3] or 'uncategorized',
            'status': row[4], 'note': row[5] or '', 'sources': row[6],
            'modules': row[7].split(',') if row[7] else [], 'artists': row[8].split(',') if row[8] else [],
            'groups': row[9].split(',') if row[9] else [], 'tags': row[10].split(',') if row[10] else [],
            'credits': row[11].split(',') if row[11] else [], 'source_urls': row[12].split(',') if row[12] else []})
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({'schema': 1, 'count': len(items), 'items': items}, ensure_ascii=False, separators=(',', ':')) + '\n', encoding='utf-8')
    db.close()

if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser(); p.add_argument('database', type=Path); p.add_argument('output', type=Path)
    a = p.parse_args(); build(a.database, a.output)
