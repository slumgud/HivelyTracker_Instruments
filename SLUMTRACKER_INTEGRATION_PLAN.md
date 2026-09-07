# SlumTracker-integrasjon: trinnvis plan

Dette dokumentet beskriver hvordan SlumTracker senere kan ta i bruk
`presets.bin`. Planen endrer ingen filer i SlumTracker og er laget som en
implementeringsspesifikasjon for en separat arbeidsgren i det prosjektet.

## Utgangspunkt

HivelyTracker_Instruments leverer:

- `ahx_instruments.sqlite` som katalogens source-of-truth.
- `build_tracker_db.py` som bygger klientfilen.
- `presets.bin` v1 med 8 894 instrumentpayloads.
- `presets_reader.c` som minimal, SQLite-fri referanseleser.
- `FORMAT.md` som binærformatkontrakt.

SlumTracker har allerede en fungerende `.ins`/`THXI`-decoder i
`src/pt2_ahx_preset.c` og et testprogram i `tools/ahx_preset_test.c`. Den nye
integrasjonen skal gjenbruke denne dekodingen etter at en BIN-record er lest;
det skal ikke bygges en ny AHX-semantikk i katalogverktøyet.

## Trinn 1 – isolert referanseimplementasjon

Opprett i SlumTracker en egen modul, for eksempel `src/slum_preset_bank.c/.h`,
uten endring av eksisterende `.ins`-import.

API-et bør være:

```c
typedef struct slumPresetBank slumPresetBank_t;

bool slumPresetBankLoad(const UNICHAR *path, slumPresetBank_t **out);
void slumPresetBankFree(slumPresetBank_t *bank);
size_t slumPresetBankCount(const slumPresetBank_t *bank);
bool slumPresetBankGet(const slumPresetBank_t *bank, size_t index,
    uint32_t *databaseId, const char **name, const uint8_t **thxi,
    size_t *thxiSize, uint8_t hash[20]);
```

Implementasjonen skal:

- kontrollere `AHXP` magic og versjon `1`;
- kontrollere header, record-boundaries og string-table offsets;
- bruke eksplisitt little-endian decoding, aldri packed C-structs;
- eie én immutable buffer for filinnholdet;
- returnere pointers som kun er gyldige så lenge banken lever;
- avvise truncering, ugyldig versjon, ugyldig offset og integer overflow.

Akseptanse: en unit-test kan laste `presets.bin`, rapportere count, hente første
record og sende payloaden til eksisterende `ahxPresetDecode()`.

## Trinn 2 – hash- og payload-verifisering

Legg til SHA-1-verifisering i SlumTracker-bankmodulen, eller bruk en allerede
godkjent intern SHA-1-implementasjon. Hashen i hver record skal verifiseres mot
hele `THXI`-payloaden.

Ved feil skal hele banken avvises atomisk. Det skal ikke være mulig å få en
delvis lastet presetbank inn i UI eller runtime.

Akseptanse:

- én bit endret i payload gir kontrollert load failure;
- én bit endret i hash gir kontrollert load failure;
- eksisterende `.ins`-import og playback påvirkes ikke.

## Trinn 3 – CMake og testfixture

Legg i SlumTracker til en separat testtarget, eksempelvis
`slum-preset-bank-test`, uten SDL-editoravhengighet hvis mulig.

Testfixtureen skal dekke:

1. gyldig header og én record;
2. flere records og string offsets;
3. tom string;
4. truncert header, record og payload;
5. feil magic og versjon;
6. ugyldig string offset;
7. hash mismatch;
8. videre dekoding med `ahxPresetDecode()`;
9. round-trip mot en liten fixture-BIN generert fra SQLite-testdata.

Registrer testen med CTest. Ikke bruk hele 1,5 MB-biblioteket som eneste test;
den lille fixtureen skal være rask og ligge stabilt i SlumTracker-testmiljøet.

## Trinn 4 – katalogoppslag i UI

Legg et read-only presetbank-oppslag ved siden av dagens filvelger.

Første UI-versjon skal kun tilby:

- laste en valgt `presets.bin`;
- vise navn og antall;
- søke på navn;
- velge record;
- laste valgt `THXI`-payload inn i eksisterende AHX-instrument-slot.

Den skal ikke skrive tilbake til BIN-filen, SQLite eller metadata. Runtime skal
fortsatt eie en kopi av dekodet `ahxPreset_t`/synth-instrument på samme måte som
ved `.ins`-import.

Akseptanse: valg av et bibliotekspreset gir samme AHX-data som valg av den
tilsvarende `.ins`-filen.

## Trinn 5 – build-pipeline fra SlumTracker

SlumTracker skal ikke kjøre Python eller åpne SQLite under runtime. Velg én av
følgende buildstrategier i SlumTracker-arbeidsgrenen:

### Anbefalt: ferdig generert input

- `presets.bin` bygges i HivelyTracker_Instruments.
- SlumTracker-builden mottar filen via en dokumentert input-path eller release-
  artifact.
- CMake kopierer filen til runtime-output ved behov.
- En CMake/CTest smoke-test validerer at filen kan lastes.

### Alternativ: eksplisitt lokal build-step

- CMake får en valgfri `SLUM_PRESET_DB`-path.
- En custom command kjører `build_tracker_db.py` kun når Python og SQLite-input
  er tilgjengelig.
- Runtime-builds uten databaseverktøy skal fortsatt fungere med en allerede
  generert `presets.bin`.

Ikke legg en automatisk nettverksnedlasting inn i CMake.

## Trinn 6 – migrering og kompatibilitet

- Behold `.ins`-importen som fallback i første integrasjonsversjon.
- Behold eksisterende native `.slm`-lagring uendret.
- Ikke endre `THXI`-decoderens semantics.
- `database_id` brukes kun som katalogreferanse; SHA-1 er stabil identitet.
- Avvis ukjent BIN-versjon med tydelig feilmelding og fall tilbake til `.ins`.
- Ikke bland metadata fra SQLite inn i AHX råpayload.

## Trinn 7 – ytelse og releasekontroll

Mål før integrasjonen erklæres klar:

- lasting av bank skjer uten merkbar blokkering av editoren;
- én immutable bankbuffer brukes per lastet fil;
- minst ett preset kan lastes og spilles på AHX-kanal;
- `3 PCM + 1 AHX`, `2 PCM + 2 AHX` og `4 AHX`-matrisen passerer;
- eksisterende `slum-ahx-preset-test` og nye banktester passerer;
- releasepakken inneholder formatversjon og SHA-256 for `presets.bin`;
- buildloggen viser hvilken BIN-fil som ble brukt.

## Handoff mellom prosjektene

HivelyTracker_Instruments leverer til SlumTracker:

1. `FORMAT.md` og denne planen;
2. `presets.bin` v1;
3. SHA-256 for filen;
4. `presets_reader.c` som wire-formatreferanse;
5. testkommandoen `python -m unittest -v test_ahx_database.py`;
6. eksempelkommandoen `python build_tracker_db.py ahx_instruments.sqlite -o presets.bin`.

Alle endringer i SlumTracker skal gjøres i en separat gren og verifiseres mot
samme `presets.bin`-artifact. Ingen SQLite-filer skal kopieres inn i
SlumTracker-runtime.
