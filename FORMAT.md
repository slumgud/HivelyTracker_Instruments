# AHX instrument archive formats

## SQLite schema v1

`instrument` is the deduplicated source of truth. `hash_sha1` is SHA-1 of the
complete `THXI` payload (magic plus the 22-byte AHX instrument header and
playlist bytes); the display name is deliberately not part of the identity.
`source` and `instrument_source` preserve every module/instrument occurrence.
`tag`/`instrument_tag` are free metadata for later curation. The payload is
kept as a BLOB so web clients and exporters do not depend on filesystem paths.
The nullable `artist_handle`, `artist_group`, `instrument_type`, `credits`, and
`source_url` fields are editable metadata; source fields apply to every
occurrence of a deduplicated instrument. Use `set-meta` to edit them and
`show`/`search` to inspect the catalog.

Schema migrations are applied automatically through SQLite `user_version`.
Import runs append an immutable manifest row containing the input SHA-256,
counts and reproducible error list. Metadata edits are recorded in
`metadata_history`; they never alter the raw payload or its hash.

## `presets.bin` v1

All integers are little-endian. Header: `AHXP`, `u16 version=1`, `u16 flags`,
`u32 record_count`, `u32 string_bytes`. Each record is
`u32 name_offset`, `u32 payload_size`, `u32 database_id`, 20-byte SHA-1,
followed immediately by the THXI payload. The final `string_bytes` bytes are a
NUL-terminated UTF-8 string table. Records are ordered by SQLite `id`, making
exports deterministic. SQLite remains authoritative; this file is a deployable
read-only client bundle.

Example:

```powershell
python ahx_database.py import ..\ahx_instr\index.csv -o ahx_instruments.sqlite
python ahx_database.py search Axel -d ahx_instruments.sqlite
python ahx_database.py show 1 -d ahx_instruments.sqlite
python ahx_database.py set-meta 1 --artist Example --group Demo --type lead --tag bright
python ahx_database.py export -d ahx_instruments.sqlite -o presets.bin
python ahx_database.py validate presets.bin
python build_tracker_db.py ahx_instruments.sqlite -o presets.bin
```

`presets_reader.c` is a minimal SQLite-free reference reader. It only checks
the v1 header, record boundaries and string table, and is intended as the
starting point for the SlumTracker/native implementation.
