# HivelyTracker_Instruments
A big aggregated collection of AHX instruments for HivelyTracker


Source: https://nostalgicplayer.dk/modules/format/ahx2x/

Please credit the original creators if you "borrow" a few of theese.

(fun fact: when extracting all instruments form the nostalgic-player, about half of them were "dupes" used in another track :) )

TODO:
- SQLite database and portable `presets.bin` tools are now provided by `ahx_database.py`.
-Webtool for preview with midi input/jam-mode.

See [FORMAT.md](FORMAT.md) for the versioned schema and binary format.
See [SLUMTRACKER_INTEGRATION_PLAN.md](SLUMTRACKER_INTEGRATION_PLAN.md) for the
separate, no-SQLite SlumTracker integration steps.
The static archive frontend lives in [web](web) and can be published with the
optional GitHub Pages workflow in `.github/workflows/pages.yml`.

Run the local fixture tests with:

```powershell
python -m unittest -v test_ahx_database.py
```

Useful catalog commands include `missing-metadata` and `export-curation`.
`build_tracker_db.py` is the explicit SQLite-to-SlumTracker build entrypoint;
SlumTracker runtime code only needs the resulting `presets.bin`.

For a native smoke test with MSYS2 UCRT64:

```powershell
$ucrt = 'C:\amiga\dev\msys2\ucrt64\bin'
$usr = 'C:\amiga\dev\msys2\usr\bin'
$env:Path = "$ucrt;$usr;$env:Path"
& "$ucrt\gcc.exe" -std=c99 -Wall -Wextra -pedantic presets_reader.c -o presets_reader.exe
.\presets_reader.exe presets.bin
```
