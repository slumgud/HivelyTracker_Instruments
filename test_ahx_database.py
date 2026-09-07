import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path

import ahx_database
import build_web_catalog


class DatabaseTests(unittest.TestCase):
    def test_metadata_does_not_change_payload_hash(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / 'test.sqlite'
            db = ahx_database.db_connect(db_path)
            payload = b'THXI' + bytes(range(22))
            digest = hashlib.sha1(payload).hexdigest()
            db.execute('INSERT INTO instrument(hash_sha1,name,payload,playlist_length) VALUES(?,?,?,?)',
                       (digest, 'lead', payload, 0))
            db.commit(); db.close()
            ahx_database.set_metadata(db_path, 1, name='curated lead', instrument_type='lead',
                                      artist='handle', group='group', note='checked', tags=['bright'])
            db = sqlite3.connect(db_path)
            self.assertEqual(db.execute('SELECT hash_sha1,payload,metadata_status FROM instrument WHERE id=1').fetchone(),
                             (digest, payload, 'confirmed'))
            self.assertEqual(db.execute('SELECT COUNT(*) FROM metadata_history').fetchone()[0], 3)
            db.close()

    def test_bin_round_trip_and_corruption(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); db_path = root / 'test.sqlite'; out = root / 'presets.bin'
            db = ahx_database.db_connect(db_path)
            payload = b'THXI' + bytes(range(22))
            db.execute('INSERT INTO instrument(hash_sha1,name,payload,playlist_length) VALUES(?,?,?,?)',
                       (hashlib.sha1(payload).hexdigest(), 'fixture', payload, 0))
            db.commit(); db.close()
            ahx_database.export_bin(db_path, out)
            ahx_database.validate_bin(out)
            corrupt = bytearray(out.read_bytes()); corrupt[-1] ^= 1
            bad = root / 'bad.bin'; bad.write_bytes(corrupt)
            with self.assertRaises(ValueError): ahx_database.validate_bin(bad)

    def test_export_is_deterministic(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); db_path = root / 'test.sqlite'
            db = ahx_database.db_connect(db_path)
            for name in ('second', 'first'):
                payload = b'THXI' + name.encode('ascii')
                db.execute('INSERT INTO instrument(hash_sha1,name,payload,playlist_length) VALUES(?,?,?,?)',
                           (hashlib.sha1(payload).hexdigest(), name, payload, 0))
            db.commit(); db.close()
            one, two = root / 'one.bin', root / 'two.bin'
            ahx_database.export_bin(db_path, one); ahx_database.export_bin(db_path, two)
            self.assertEqual(one.read_bytes(), two.read_bytes())

    def test_curation_import_requires_matching_hash(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); db_path = root / 'test.sqlite'; curation = root / 'curation.json'
            payload = b'THXI' + bytes(range(22)); digest = hashlib.sha1(payload).hexdigest()
            db = ahx_database.db_connect(db_path)
            db.execute('INSERT INTO instrument(hash_sha1,name,payload,playlist_length) VALUES(?,?,?,?)', (digest, 'fixture', payload, 0))
            db.commit(); db.close()
            curation.write_text('{"1":{"hash":"wrong","type":"lead"}}', encoding='utf-8')
            self.assertEqual(ahx_database.import_curation(db_path, curation), 1)
            db = sqlite3.connect(db_path); self.assertIsNone(db.execute('SELECT instrument_type FROM instrument WHERE id=1').fetchone()[0]); db.close()

    def test_curation_import_applies_metadata_and_tags(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); db_path = root / 'test.sqlite'; curation = root / 'curation.json'
            payload = b'THXI' + bytes(range(22)); digest = hashlib.sha1(payload).hexdigest()
            db = ahx_database.db_connect(db_path)
            db.execute('INSERT INTO instrument(hash_sha1,name,payload,playlist_length) VALUES(?,?,?,?)', (digest, 'fixture', payload, 0))
            db.commit(); db.close()
            curation.write_text('{"1":{"hash":"' + digest + '","type":"bass","tags":"low, analog","note":"checked"}}', encoding='utf-8')
            self.assertEqual(ahx_database.import_curation(db_path, curation), 0)
            db = sqlite3.connect(db_path)
            self.assertEqual(db.execute('SELECT instrument_type,curator_note FROM instrument WHERE id=1').fetchone(), ('bass', 'checked'))
            self.assertEqual(db.execute('SELECT COUNT(*) FROM instrument_tag WHERE instrument_id=1').fetchone()[0], 2)
            db.close()

    def test_web_catalog_read_model_contains_provenance(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); db_path = root / 'test.sqlite'; output = root / 'catalog.json'
            payload = b'THXI' + bytes(range(22)); digest = hashlib.sha1(payload).hexdigest()
            db = ahx_database.db_connect(db_path)
            db.execute('INSERT INTO instrument(hash_sha1,name,payload,playlist_length,instrument_type) VALUES(?,?,?,?,?)',
                       (digest, 'fixture', payload, 0, 'lead'))
            db.execute('INSERT INTO source(module_path,module_title,instrument_number,instrument_name,artist_handle,artist_group,credits,source_url) VALUES(?,?,?,?,?,?,?,?)',
                       ('demo.ahx', 'Demo Song', 1, 'fixture', 'Artist', 'Group', 'Credit', 'https://example.test'))
            db.execute('INSERT INTO instrument_source VALUES(1,1)')
            db.execute('INSERT INTO tag(name) VALUES(?)', ('bright',)); db.execute('INSERT INTO instrument_tag VALUES(1,1)')
            db.commit(); db.close()
            build_web_catalog.build(db_path, output)
            item = __import__('json').loads(output.read_text(encoding='utf-8'))['items'][0]
            self.assertEqual(item['type'], 'lead'); self.assertEqual(item['modules'], ['Demo Song'])
            self.assertEqual(item['artists'], ['Artist']); self.assertEqual(item['groups'], ['Group'])
            self.assertEqual(item['credits'], ['Credit']); self.assertEqual(item['source_urls'], ['https://example.test'])
            self.assertEqual(item['tags'], ['bright'])


if __name__ == '__main__':
    unittest.main()
