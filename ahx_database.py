#!/usr/bin/env python3
"""SQLite catalog and portable preset bundle tools for AHX instruments."""
from __future__ import annotations
import argparse, csv, hashlib, json, sqlite3, struct, sys
from pathlib import Path

SCHEMA = '''
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS instrument (
 id INTEGER PRIMARY KEY, hash_sha1 TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
 format TEXT NOT NULL DEFAULT 'THXI', payload BLOB NOT NULL,
 playlist_length INTEGER NOT NULL, instrument_type TEXT, metadata_status TEXT NOT NULL DEFAULT 'unknown',
 curator_note TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS source (
 id INTEGER PRIMARY KEY, module_path TEXT NOT NULL, module_title TEXT NOT NULL,
 module_version INTEGER, instrument_number INTEGER NOT NULL, instrument_name TEXT,
 artist_handle TEXT, artist_group TEXT, credits TEXT, source_url TEXT,
 UNIQUE(module_path, instrument_number)
);
CREATE TABLE IF NOT EXISTS instrument_source (
 instrument_id INTEGER NOT NULL REFERENCES instrument(id) ON DELETE CASCADE,
 source_id INTEGER NOT NULL REFERENCES source(id) ON DELETE CASCADE,
 PRIMARY KEY(instrument_id, source_id)
);
CREATE TABLE IF NOT EXISTS tag (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE);
CREATE TABLE IF NOT EXISTS instrument_tag (
 instrument_id INTEGER NOT NULL REFERENCES instrument(id) ON DELETE CASCADE,
 tag_id INTEGER NOT NULL REFERENCES tag(id) ON DELETE CASCADE,
 PRIMARY KEY(instrument_id, tag_id)
);
CREATE INDEX IF NOT EXISTS instrument_name_idx ON instrument(name);
CREATE INDEX IF NOT EXISTS source_title_idx ON source(module_title);
'''
BIN_MAGIC = b'AHXP'; BIN_VERSION = 1
SCHEMA_VERSION = 3

def db_connect(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.executescript(SCHEMA)
    version = db.execute('PRAGMA user_version').fetchone()[0]
    if version < 2:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS import_manifest (
          id INTEGER PRIMARY KEY, source_path TEXT NOT NULL, source_sha256 TEXT NOT NULL,
          extractor_version TEXT NOT NULL, modules_found INTEGER NOT NULL,
          modules_imported INTEGER NOT NULL, instrument_occurrences INTEGER NOT NULL,
          unique_instruments INTEGER NOT NULL, errors_json TEXT NOT NULL,
          imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS metadata_history (
          id INTEGER PRIMARY KEY, instrument_id INTEGER NOT NULL REFERENCES instrument(id),
          field_name TEXT NOT NULL, old_value TEXT, new_value TEXT,
          actor TEXT NOT NULL, changed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        PRAGMA user_version=2;
        ''')
        version = 2
    if version < 3:
        columns = {row[1] for row in db.execute('PRAGMA table_info(instrument)')}
        if 'metadata_status' not in columns:
            db.execute("ALTER TABLE instrument ADD COLUMN metadata_status TEXT NOT NULL DEFAULT 'unknown'")
        if 'curator_note' not in columns:
            db.execute('ALTER TABLE instrument ADD COLUMN curator_note TEXT')
        db.execute('PRAGMA user_version=3')
    return db

def import_index(db_path: Path, index: Path) -> tuple[int, int]:
    db = db_connect(db_path); instruments = sources = 0; errors = []; module_paths = set()
    # Old index.csv files contain absolute paths from the extraction machine.
    # Resolve by filename under the index's by_module tree when those paths
    # are no longer valid, without depending on the original drive or root.
    preset_files = {p.name: p for p in (index.parent / 'library').rglob('*.ins')}
    with index.open(newline='', encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            module_paths.add(row['module'])
            # The library filename contains the content hash and is unique;
            # use it first so duplicate module filenames cannot collide.
            preset = Path(row['library_preset'])
            if not preset.is_file():
                preset = preset_files.get(Path(row['library_preset']).name, Path())
            if not preset.is_file():
                errors.append({'module': row['module'], 'instrument': row['instrument_number'], 'error': 'preset not found'})
                continue
            try:
                raw = preset.read_bytes()
            except OSError as exc:
                errors.append({'module': row['module'], 'instrument': row['instrument_number'], 'error': str(exc)})
                continue
            if len(raw) < 4 or raw[:4] != b'THXI':
                errors.append({'module': row['module'], 'instrument': row['instrument_number'], 'error': 'invalid THXI magic'})
                continue
            payload = raw[:-1] if raw.endswith(b'\0') else raw
            name = row['instrument_name'] or row['fallback_name']
            digest = hashlib.sha1(payload).hexdigest()
            cur = db.execute('''INSERT INTO instrument(hash_sha1,name,payload,playlist_length)
                VALUES(?,?,?,?) ON CONFLICT(hash_sha1) DO UPDATE SET name=instrument.name''',
                (digest, name, payload, int(row['playlist_length'])))
            iid = db.execute('SELECT id FROM instrument WHERE hash_sha1=?', (digest,)).fetchone()[0]
            cur = db.execute('''INSERT OR IGNORE INTO source(module_path,module_title,module_version,instrument_number,instrument_name)
                VALUES(?,?,?,?,?)''', (row['module'], row['module_title'], int(row['module_version']), int(row['instrument_number']), row['instrument_name']))
            sid = db.execute('SELECT id FROM source WHERE module_path=? AND instrument_number=?', (row['module'], int(row['instrument_number']))).fetchone()[0]
            db.execute('INSERT OR IGNORE INTO instrument_source VALUES(?,?)', (iid, sid))
            instruments += 1; sources += cur.rowcount
    source_bytes = index.read_bytes()
    db.execute('''INSERT INTO import_manifest(source_path,source_sha256,extractor_version,
        modules_found,modules_imported,instrument_occurrences,unique_instruments,errors_json)
        VALUES(?,?,?,?,?,?,?,?)''', (str(index), hashlib.sha256(source_bytes).hexdigest(),
        'ahx_database/3', len(module_paths), len(module_paths) - len({e['module'] for e in errors}),
        instruments, db.execute('SELECT COUNT(*) FROM instrument').fetchone()[0], json.dumps(errors)))
    db.commit(); db.close(); return instruments, sources

def search(db_path: Path, term: str):
    db = db_connect(db_path)
    rows = db.execute('''SELECT i.id,i.hash_sha1,i.name,COUNT(s.id),i.playlist_length
      FROM instrument i LEFT JOIN instrument_source x ON x.instrument_id=i.id
      LEFT JOIN source s ON s.id=x.source_id WHERE i.name LIKE ? OR s.module_title LIKE ?
      GROUP BY i.id ORDER BY i.name COLLATE NOCASE''', (f'%{term}%', f'%{term}%')).fetchall()
    for r in rows: print(f'{r[0]}\t{r[2]}\t{r[1]}\t{r[3]} sources\tplaylist={r[4]}')
    db.close(); return len(rows)

def show(db_path: Path, instrument_id: int):
    db = db_connect(db_path)
    row = db.execute('''SELECT i.id,i.hash_sha1,i.name,i.instrument_type,i.metadata_status,i.curator_note,
        GROUP_CONCAT(DISTINCT s.module_title),COUNT(DISTINCT s.id)
        FROM instrument i LEFT JOIN instrument_source x ON x.instrument_id=i.id
        LEFT JOIN source s ON s.id=x.source_id WHERE i.id=? GROUP BY i.id''', (instrument_id,)).fetchone()
    if row is None:
        raise ValueError(f'instrument {instrument_id} not found')
    print(json.dumps({'id':row[0], 'hash_sha1':row[1], 'name':row[2],
        'instrument_type':row[3], 'metadata_status':row[4], 'curator_note':row[5],
        'modules':row[6].split(',') if row[6] else [], 'source_count':row[7]}, ensure_ascii=False, indent=2))
    db.close()

def set_metadata(db_path: Path, instrument_id: int, *, name=None, instrument_type=None,
                 artist=None, group=None, credits=None, source_url=None, note=None, tags=()):
    db = db_connect(db_path)
    old = db.execute('SELECT name,instrument_type FROM instrument WHERE id=?', (instrument_id,)).fetchone()
    if old is None:
        raise ValueError(f'instrument {instrument_id} not found')
    if name is not None or instrument_type is not None:
        db.execute('UPDATE instrument SET name=COALESCE(?,name), instrument_type=COALESCE(?,instrument_type), curator_note=COALESCE(?,curator_note), metadata_status=CASE WHEN ? IS NULL THEN metadata_status ELSE ? END WHERE id=?',
                   (name, instrument_type, note, instrument_type, 'confirmed', instrument_id))
        if name is not None and name != old[0]:
            db.execute('INSERT INTO metadata_history(instrument_id,field_name,old_value,new_value,actor) VALUES(?,?,?,?,?)', (instrument_id,'name',old[0],name,'cli'))
        if instrument_type is not None and instrument_type != old[1]:
            db.execute('INSERT INTO metadata_history(instrument_id,field_name,old_value,new_value,actor) VALUES(?,?,?,?,?)', (instrument_id,'instrument_type',old[1],instrument_type,'cli'))
    source_ids = [r[0] for r in db.execute('SELECT source_id FROM instrument_source WHERE instrument_id=?', (instrument_id,))]
    for sid in source_ids:
        db.execute('''UPDATE source SET artist_handle=COALESCE(?,artist_handle), artist_group=COALESCE(?,artist_group),
            credits=COALESCE(?,credits), source_url=COALESCE(?,source_url) WHERE id=?''',
            (artist, group, credits, source_url, sid))
    for tag in tags:
        db.execute('INSERT OR IGNORE INTO tag(name) VALUES(?)', (tag,))
        tid = db.execute('SELECT id FROM tag WHERE name=?', (tag,)).fetchone()[0]
        db.execute('INSERT OR IGNORE INTO instrument_tag VALUES(?,?)', (instrument_id, tid))
        db.execute('INSERT INTO metadata_history(instrument_id,field_name,new_value,actor) VALUES(?,?,?,?)', (instrument_id,'tag',tag,'cli'))
    db.commit(); db.close()

def missing_metadata(db_path: Path):
    db = db_connect(db_path)
    rows = db.execute('SELECT id,name,hash_sha1 FROM instrument WHERE metadata_status != "confirmed" OR instrument_type IS NULL ORDER BY id').fetchall()
    for row in rows: print(f'{row[0]}\t{row[1]}\t{row[2]}')
    db.close(); return len(rows)

def export_curation(db_path: Path, out: Path):
    db = db_connect(db_path)
    rows = db.execute('''SELECT i.id,i.name,i.hash_sha1,i.instrument_type,i.metadata_status,i.curator_note,
        GROUP_CONCAT(DISTINCT s.artist_handle),GROUP_CONCAT(DISTINCT s.artist_group),GROUP_CONCAT(DISTINCT s.credits),
        GROUP_CONCAT(DISTINCT t.name)
        FROM instrument i LEFT JOIN instrument_source x ON x.instrument_id=i.id LEFT JOIN source s ON s.id=x.source_id
        LEFT JOIN instrument_tag it ON it.instrument_id=i.id LEFT JOIN tag t ON t.id=it.tag_id GROUP BY i.id ORDER BY i.id''').fetchall()
    fields = ['id','name','hash_sha1','instrument_type','metadata_status','curator_note','artist_handles','groups','credits','tags']
    with out.open('w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f); writer.writerow(fields); writer.writerows(rows)
    db.close()

def import_curation(db_path: Path, source: Path, actor: str = 'curation-import'):
    """Apply browser-exported metadata, refusing stale or mismatched hashes."""
    changes = 0; rejected = []
    data = json.loads(source.read_text(encoding='utf-8'))
    db = db_connect(db_path)
    for raw_id, item in data.items():
        try: iid = int(raw_id)
        except (TypeError, ValueError): rejected.append((raw_id, 'invalid id')); continue
        row = db.execute('SELECT hash_sha1,name,instrument_type,curator_note FROM instrument WHERE id=?', (iid,)).fetchone()
        if row is None: rejected.append((iid, 'instrument not found')); continue
        if item.get('hash') and item['hash'] != row[0]:
            rejected.append((iid, 'hash mismatch')); continue
        touched = False
        new_type = item.get('type') or row[2]
        note = item.get('note') if 'note' in item else row[3]
        if new_type != row[2] or note != row[3]:
            db.execute('UPDATE instrument SET instrument_type=?, curator_note=?, metadata_status=? WHERE id=?',
                       (new_type, note, 'confirmed', iid))
            if new_type != row[2]: db.execute('INSERT INTO metadata_history(instrument_id,field_name,old_value,new_value,actor) VALUES(?,?,?,?,?)', (iid,'instrument_type',row[2],new_type,actor))
            if note != row[3]: db.execute('INSERT INTO metadata_history(instrument_id,field_name,old_value,new_value,actor) VALUES(?,?,?,?,?)', (iid,'curator_note',row[3],note,actor))
            touched = True
        source_ids = [r[0] for r in db.execute('SELECT source_id FROM instrument_source WHERE instrument_id=?', (iid,))]
        for sid in source_ids:
            if item.get('artist') or item.get('group') or item.get('credits') or item.get('source_url'):
                db.execute('UPDATE source SET artist_handle=COALESCE(?,artist_handle), artist_group=COALESCE(?,artist_group), credits=COALESCE(?,credits), source_url=COALESCE(?,source_url) WHERE id=?',
                           (item.get('artist') or None, item.get('group') or None, item.get('credits') or None, item.get('source_url') or None, sid)); touched = True
        if 'tags' in item:
            touched = True
            db.execute('DELETE FROM instrument_tag WHERE instrument_id=?', (iid,))
            for tag in {x.strip() for x in str(item.get('tags') or '').split(',') if x.strip()}:
                db.execute('INSERT OR IGNORE INTO tag(name) VALUES(?)', (tag,))
                tid = db.execute('SELECT id FROM tag WHERE name=?', (tag,)).fetchone()[0]
                db.execute('INSERT OR IGNORE INTO instrument_tag VALUES(?,?)', (iid, tid))
        if touched: changes += 1
    db.commit(); db.close()
    print(json.dumps({'changed': changes, 'rejected': rejected}, ensure_ascii=False))
    return 1 if rejected else 0

def export_bin(db_path: Path, out: Path):
    db = db_connect(db_path); rows = db.execute('SELECT id,hash_sha1,name,payload FROM instrument ORDER BY id').fetchall()
    strings = bytearray(); records = bytearray()
    for iid, digest, name, payload in rows:
        nb = name.encode('utf-8'); no = len(strings); strings += nb + b'\0'
        records += struct.pack('<III20s', no, len(payload), iid, bytes.fromhex(digest)) + payload
    header = struct.pack('<4sHHII', BIN_MAGIC, BIN_VERSION, 0, len(rows), len(strings))
    out.parent.mkdir(parents=True, exist_ok=True); out.write_bytes(header + records + strings); db.close()

def validate_bin(path: Path):
    data = path.read_bytes(); hs = struct.calcsize('<4sHHII')
    if len(data) < hs: raise ValueError('truncated header')
    magic, version, flags, count, string_len = struct.unpack_from('<4sHHII', data)
    if magic != BIN_MAGIC or version != BIN_VERSION: raise ValueError('unsupported presets.bin')
    p = hs; names = len(data) - string_len; seen = set(); offsets = []
    for _ in range(count):
        if p + 32 > names: raise ValueError('truncated record')
        no, size, iid, digest = struct.unpack_from('<III20s', data, p); p += 32
        if p + size > names: raise ValueError('truncated payload')
        if hashlib.sha1(data[p:p+size]).digest() != digest: raise ValueError(f'hash mismatch for {iid}')
        seen.add(iid); offsets.append(no); p += size
    if p != names: raise ValueError('record/string boundary mismatch')
    strings = data[names:]
    for offset in offsets:
        if offset >= len(strings) or strings.find(b'\0', offset) < 0:
            raise ValueError('invalid string-table offset')
    print(f'valid presets.bin v{version}: {count} instruments, {string_len} string bytes')

def main(argv=None):
    ap=argparse.ArgumentParser(); sub=ap.add_subparsers(dest='cmd',required=True)
    x=sub.add_parser('import'); x.add_argument('index',type=Path); x.add_argument('-o','--db',type=Path,default=Path('ahx_instruments.sqlite'))
    s=sub.add_parser('search'); s.add_argument('term'); s.add_argument('-d','--db',type=Path,default=Path('ahx_instruments.sqlite'))
    sh=sub.add_parser('show'); sh.add_argument('id',type=int); sh.add_argument('-d','--db',type=Path,default=Path('ahx_instruments.sqlite'))
    m=sub.add_parser('set-meta'); m.add_argument('id',type=int); m.add_argument('-d','--db',type=Path,default=Path('ahx_instruments.sqlite'))
    m.add_argument('--name'); m.add_argument('--type',dest='instrument_type'); m.add_argument('--artist')
    m.add_argument('--group'); m.add_argument('--credits'); m.add_argument('--source-url'); m.add_argument('--note'); m.add_argument('--tag',action='append',default=[])
    mm=sub.add_parser('missing-metadata'); mm.add_argument('-d','--db',type=Path,default=Path('ahx_instruments.sqlite'))
    c=sub.add_parser('export-curation'); c.add_argument('-d','--db',type=Path,default=Path('ahx_instruments.sqlite')); c.add_argument('-o','--out',type=Path,default=Path('curation.csv'))
    ic=sub.add_parser('import-curation'); ic.add_argument('file',type=Path); ic.add_argument('-d','--db',type=Path,default=Path('ahx_instruments.sqlite')); ic.add_argument('--actor',default='curation-import')
    e=sub.add_parser('export'); e.add_argument('-d','--db',type=Path,default=Path('ahx_instruments.sqlite')); e.add_argument('-o','--out',type=Path,default=Path('presets.bin'))
    v=sub.add_parser('validate'); v.add_argument('file',type=Path)
    a=ap.parse_args(argv)
    if a.cmd=='import': print('imported', import_index(a.db,a.index))
    elif a.cmd=='search': print(f'{search(a.db,a.term)} matches')
    elif a.cmd=='show': show(a.db,a.id)
    elif a.cmd=='set-meta': set_metadata(a.db,a.id,name=a.name,instrument_type=a.instrument_type,artist=a.artist,group=a.group,credits=a.credits,source_url=a.source_url,note=a.note,tags=a.tag)
    elif a.cmd=='missing-metadata': print(f'{missing_metadata(a.db)} instruments need metadata')
    elif a.cmd=='export-curation': export_curation(a.db,a.out); print(a.out)
    elif a.cmd=='import-curation': return import_curation(a.db,a.file,a.actor)
    elif a.cmd=='export': export_bin(a.db,a.out); validate_bin(a.out)
    else: validate_bin(a.file)
if __name__=='__main__': main()
