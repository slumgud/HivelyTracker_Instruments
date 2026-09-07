# AHX Instrument Archive webfront

This is a static GitHub Pages frontend. It has no SQLite or SlumTracker
runtime dependency.

## Open the web app

**[Open the AHX Instrument Archive](https://slumgud.github.io/HivelyTracker_Instruments/)**

The live app lets you search the instrument catalogue, inspect original module
sources, preview voices, and keep local curation notes in the browser.

Build the read model and copy the portable preset bank before serving:

```powershell
$py = 'C:\Users\eplej\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $py build_web_catalog.py ahx_instruments.sqlite web\data\catalog.json
New-Item -ItemType Directory -Force web\data | Out-Null
Copy-Item presets.bin web\data\presets.bin -Force
```

The curation panel edits type, tags, artist/handle, group, credits, source URL
and curator note. The preview is an intentionally lightweight WebAudio approximation of the
selected THXI voice. The raw payload remains available for a future WASM/AHX
preview engine.

Exported `ahx-curation.json` can be reviewed and applied to the master database
explicitly:

```powershell
python ahx_database.py import-curation ahx-curation.json -d ahx_instruments.sqlite --actor web-review
```

The importer checks the exported SHA-1 hash before changing metadata, so stale
browser exports cannot silently edit a different instrument.

The release read model can be checked locally with:

```powershell
python validate_web.py web\data\catalog.json web\data\presets.bin
```
