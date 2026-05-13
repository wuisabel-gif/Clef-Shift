# Clef Shift

Small C++ starter for translating notes between clefs.

Clef Shift is also a melody adaptation project:

- `transposition`: changing pitch by a fixed interval
- `octave displacement`: moving the same melody up or down by octaves
- `register shift`: placing the same melodic shape into a different pitch range
- `arrangement` or `transcription`: adapting music for another instrument

In plain language, the goal is:

`A system that preserves melodic structure while adapting pitch register for different instruments.`

It supports these clefs:

- `treble` = 高音谱号
- `bass` = 低音谱号
- `alto` = 中音谱号

It supports two useful modes:

- `translate`: keep the same pitch and show where it appears in another clef
- `arrange`: shift notes by octave when needed so they sit in a more cello-friendly range

It also includes a LilyPond-based path for producing clean engraved PDFs.

It now also includes a first structured-score pipeline:

- image or PDF upload
- best-effort OCR note detection
- note data model
- MusicXML generation
- regenerated notation preview from structured note data

## Run Locally

For the website with upload preview and OCR support:

```bash
python3 server.py
```

Then open:

```text
http://127.0.0.1:8000
```

Important:

- use `server.py` for the website, not `python3 -m http.server`
- image and PDF uploads preview instantly in the browser
- the page now sends uploaded images and PDFs to a local OCR endpoint automatically
- OCR currently looks for note names like `A4`, `Bb3`, and `F#5`
- the page can generate and download MusicXML from the structured score pipeline
- general text OCR works better than true sheet-music recognition, so scanned notation images may still need manual note entry

## Project Language

If you want to describe the project clearly on GitHub, a resume, or a portfolio page, these are strong terms:

- `Melody Transposition Engine`
- `Register-Aware Sheet Music Converter`
- `Cross-Instrument Music Transcriber`
- `Octave-Shift Music Converter`

The core musical idea is:

- same melody
- different register
- sometimes different clef
- sometimes different instrument range

Examples:

- violin to cello: same melody, often shifted down by one or two octaves
- flute to bassoon: same melody, lower register
- violin to viola: same melody, different clef and slightly lower range

## Build

```bash
clang++ -std=c++17 -Wall -Wextra -pedantic main.cpp -o clefshift
```

## Examples

Treble to bass:

```bash
./clefshift --mode translate --from treble --to bass "A4 B4 C5"
```

Bass to alto:

```bash
./clefshift --mode translate --from bass --to alto "F2 C3 G3"
```

Alto to treble:

```bash
./clefshift --mode translate --from alto --to treble "C4 D4 E4"
```

Arrangement for cello:

```bash
./clefshift --mode arrange "E5 F5 G5 A5"
```

Expected arrange result for that example:

- `E5 -> E4`
- `F5 -> F4`
- `G5 -> G4`
- `A5 -> A4`

## Clean PDF Output

There is a starter LilyPond score at `scores/example_excerpt_cello.ly`.

Render it to PDF with:

```bash
./render_pdf.sh scores/example_excerpt_cello.ly
```

Notes:

- `render_pdf.sh` requires `lilypond` to be installed locally
- the included example is a manual starter transcription from the screenshot, so it should be proofread against the original image before treating it as final engraving
- once LilyPond is installed, the output PDF will be clean, vector-based sheet music

## Notes

- Input format is note names like `C4`, `F#5`, or `Bb3`
- `translate` preserves pitch and changes only the clef view
- `arrange` is intentionally simple: if a note is too high for comfortable cello writing, move it down by octaves when possible
- from a programming perspective, the project represents melody as pitch, preserves interval structure, and adapts octave placement for target range
- uploaded images and PDFs now go through a local OCR step in the website
- OCR is best-effort and is not full music notation recognition yet
- structured notes can now be exported as MusicXML for downstream engraving
