# Clef Shift

Clef Shift is a music accessibility and adaptation project built around a simple idea:

`keep the musical idea the same, but make it easier to read, play, and reuse across instruments`

As someone who is not a strong sight reader, especially when switching between clefs or reading unfamiliar ranges, I wanted a tool that lowers that barrier. Clef Shift helps turn that frustration into something practical by translating notation between clefs and reshaping pitch register into a form that feels more approachable for performance and study.

## Project Overview

Clef Shift explores several related musical transformations:

- `transposition`: changing pitch by a fixed interval
- `octave displacement`: moving the same melody up or down by octaves
- `register shift`: preserving melodic shape while placing it in a more useful range
- `arrangement` or `transcription`: adapting material for another instrument

In plain language, the project is centered on:

`a system that preserves melodic structure while adapting pitch register for readability and instrument fit`

The long-term goal is to reach a more autonomous, streamlined workflow: starting from original sheet music, recognizing the notation structure, identifying the clef automatically, converting the material into structured musical data, and generating a readable adapted output with as little manual intervention as possible.

## Why It Matters

For musicians who do not sight read fluently, the difficulty is often not understanding the music itself, but decoding how it is written on the page. A line that is completely manageable in one clef can feel much harder in another. Clef Shift is designed to support that gap by making the same musical content easier to access without losing its identity.

This is especially useful when:

- comparing the same passage across different clefs
- preparing music for cello or another instrument with a different comfortable range
- studying melodic contour without getting stuck on notation friction
- turning rough source material into a cleaner engraved result

## Core Capabilities

The project currently supports these clefs:

- `treble`
- `bass`
- `alto`

It includes two main translation modes:

- `translate`: preserve pitch and show where the notes appear in another clef
- `arrange`: shift notes by octave when needed so they sit in a more cello-friendly range

It also includes a LilyPond engraving path for producing clean PDF sheet music and a first-pass structured score pipeline for moving from uploaded source material into editable notation data.

## Structured Score Pipeline

The current pipeline supports:

- image or PDF upload
- best-effort OCR note detection
- note data modeling
- MusicXML generation
- regenerated notation preview from structured note data

This makes Clef Shift more than a clef-conversion utility. It also begins to function as a bridge between rough visual music input and cleaner, reusable notation output.

At its current stage, that pipeline is still limited. The OCR layer is not yet a full sheet-music reader, and one of the main challenges is reliably recognizing the clef from the original sheet music before the rest of the translation process can become fully autonomous.

## Demonstration Examples

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

## Local Demo

For the browser-based demo with upload preview and OCR support:

```bash
python3 server.py
```

Then open:

```text
http://127.0.0.1:8000
```

Important demo notes:

- use `server.py` for the website, not `python3 -m http.server`
- image and PDF uploads preview instantly in the browser
- uploaded images and PDFs are sent to a local OCR endpoint automatically
- OCR currently looks for note names such as `A4`, `Bb3`, and `F#5`
- the page can generate and download MusicXML from the structured score pipeline
- the broader goal is a more autonomous end-to-end pipeline, but the current OCR is still limited when working directly from original sheet music
- general text OCR works better than full sheet-music recognition, so scanned notation may still need manual correction

## Build

```bash
clang++ -std=c++17 -Wall -Wextra -pedantic main.cpp -o clefshift
```

## Clean PDF Output

There is a starter LilyPond score at `scores/example_excerpt_cello.ly`.

Render it to PDF with:

```bash
./render_pdf.sh scores/example_excerpt_cello.ly
```

Notes:

- `render_pdf.sh` requires `lilypond` to be installed locally
- the included example is a manual starter transcription and should be proofread against the original source
- once LilyPond is installed, the output PDF is clean, vector-based sheet music

## Technical Notes

- input format is note names such as `C4`, `F#5`, or `Bb3`
- `translate` preserves pitch and changes only the clef view
- `arrange` currently uses a simple octave-shift rule for high notes that are less comfortable in cello range
- uploaded images and PDFs go through a local OCR step in the web app
- OCR is currently best-effort and not full music notation recognition
- a current limitation is reliable clef recognition from the original score image
- structured notes can be exported as MusicXML for downstream engraving
