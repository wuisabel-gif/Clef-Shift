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

## Notation Reading (Audiveris)

Real notation reading is handled by the [Audiveris](https://github.com/Audiveris/audiveris)
OMR engine, which reads pitch, octave, accidentals, key signature, and rhythm and
exports MusicXML. The server calls it as a subprocess (the in-house heuristic
detector in `omr_pipeline.py` remains only as a fallback).

Audiveris is **not bundled** — build it once beside this repo:

```bash
# Java 25 is required by Audiveris 5.10.2
brew install openjdk@25

# clone beside the Clef Shift repo (a sibling directory named audiveris-src)
git clone --depth 1 --branch 5.10.2 https://github.com/Audiveris/audiveris.git ../audiveris-src

JAVA_HOME="$(brew --prefix)/opt/openjdk@25/libexec/openjdk.jdk/Contents/Home" \
  ../audiveris-src/gradlew -p ../audiveris-src :app:installDist
```

This produces the launcher at
`../audiveris-src/app/build/install/app/bin/Audiveris`. The server finds it
automatically; override with the `AUDIVERIS_CMD` and `AUDIVERIS_JAVA_HOME`
environment variables if your paths differ. If Audiveris is absent, uploads fall
back to the heuristic detector.

### Recalibrating the confidence gate

The gate thresholds in `train/data/gate_params.json` come from a labeled corpus.
To regenerate them (needs LilyPond, Ghostscript, and Audiveris):

```bash
python3 train/corpus.py     # render score images at several quality levels
python3 train/collect.py    # run Audiveris on each, label against ground truth (slow)
python3 train/calibrate.py  # fit thresholds, write train/data/gate_params.json
```

## What Testing the Reader Taught Me

The hardest part of this project was never shifting a clef. It was trusting that
the notes on the page had been read correctly in the first place.

I can read these notes myself, so I always know what the right answer is. The
optical reader (`Audiveris`) usually agrees with me on a clean scan, but on a
lower-quality image it can do something worse than failing: it can hand back
notes that look perfectly reasonable and are simply wrong. A wrong note
presented confidently is more dangerous than no note at all.

So instead of guessing whether a read was good, I built a way to measure it. I
generate small scores where I already know every note (because I wrote them),
render the same piece at different quality levels — `clean`, `blurry`, `skewed`,
`noisy`, even a `phone-photo` look — run each one through the reader, and compare
what it returns against the truth.

A few things that taught me:

- On clean scans the reader is dependable, and on badly degraded images it
  mostly fails *safely* — it returns nothing rather than guessing. The real
  danger lives in a narrow middle band where it produces notes that are partly
  wrong.
- My first confidence cutoffs were guesses, and they let some of those
  middle-band wrong reads slip through.
- Tuning the cutoffs against labeled examples instead of my intuition caught the
  wrong reads while keeping the good ones. It also corrected a mistake of mine:
  a rule I had set too strictly would have thrown out correct music that simply
  began with a pickup measure.
- The rule I keep coming back to: `prefer no notes over wrong notes`. If the
  reader is not confident, the honest result is to say so, not to fill the page
  with something plausible.

What I have not proven yet, and want to be honest about: this is calibrated on
`generated` scores, not real-world scans; the reader still struggles with
sustained open noteheads; and the test that matters most is still a real
uploaded image that failed. So I treat the current result as
`measured, not finished`.

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
- uploads are read by Audiveris (see above), which detects pitch, octave, accidentals, key signature, and rhythm
- if Audiveris is not installed, uploads fall back to the in-house heuristic detector (filled noteheads only) and, failing that, to plain text OCR for typed note names such as `A4`, `Bb3`, `F#5`
- the page can generate and download MusicXML from the structured score pipeline
- detection is honest: when nothing is read, the app says so rather than inventing notes

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
