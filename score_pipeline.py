from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import xml.etree.ElementTree as ET


NOTE_PATTERN = re.compile(r"\b([A-Ga-g])([#b]?)(-?\d+)\b")
STEP_TO_SEMITONE = {
    "C": 0,
    "D": 2,
    "E": 4,
    "F": 5,
    "G": 7,
    "A": 9,
    "B": 11,
}
STEP_TO_DIATONIC = {
    "C": 0,
    "D": 1,
    "E": 2,
    "F": 3,
    "G": 4,
    "A": 5,
    "B": 6,
}
CLEF_DATA = {
    "treble": {"sign": "G", "line": 2},
    "bass": {"sign": "F", "line": 4},
    "alto": {"sign": "C", "line": 3},
}


@dataclass
class NoteEvent:
    step: str
    alter: int
    octave: int
    duration: int = 1
    note_type: str = "quarter"

    @property
    def token(self) -> str:
        accidental = "#" if self.alter == 1 else "b" if self.alter == -1 else ""
        return f"{self.step}{accidental}{self.octave}"

    @property
    def midi(self) -> int:
        return (self.octave + 1) * 12 + STEP_TO_SEMITONE[self.step] + self.alter


@dataclass
class ScoreData:
    title: str
    from_clef: str
    to_clef: str
    notes: list[NoteEvent]
    divisions: int = 1
    beats: int = 4
    beat_type: int = 4


def parse_note_tokens(text: str) -> list[NoteEvent]:
    notes: list[NoteEvent] = []
    for step, accidental, octave_text in NOTE_PATTERN.findall(text):
        notes.append(
            NoteEvent(
                step=step.upper(),
                alter=1 if accidental == "#" else -1 if accidental == "b" else 0,
                octave=int(octave_text),
            )
        )
    return notes


def note_from_midi(midi: int) -> NoteEvent:
    octave = midi // 12 - 1
    pitch_class = midi % 12
    reverse_map = {
        0: ("C", 0),
        1: ("C", 1),
        2: ("D", 0),
        3: ("E", -1),
        4: ("E", 0),
        5: ("F", 0),
        6: ("F", 1),
        7: ("G", 0),
        8: ("A", -1),
        9: ("A", 0),
        10: ("B", -1),
        11: ("B", 0),
    }
    step, alter = reverse_map[pitch_class]
    return NoteEvent(step=step, alter=alter, octave=octave)


def arrange_for_cello(notes: list[NoteEvent]) -> list[NoteEvent]:
    arranged: list[NoteEvent] = []
    for note in notes:
        midi = note.midi
        while midi > 69 and midi - 12 >= 36:
            midi -= 12
        while midi < 36 and midi + 12 <= 76:
            midi += 12
        arranged.append(note_from_midi(midi))
    return arranged


def build_score_data(notes_text: str, from_clef: str, to_clef: str, title: str) -> ScoreData:
    notes = parse_note_tokens(notes_text)
    if to_clef == "bass":
        notes = arrange_for_cello(notes)
    return ScoreData(title=title or "Clef Shift Output", from_clef=from_clef, to_clef=to_clef, notes=notes)


def staff_position(note: NoteEvent, clef: str) -> str:
    bottoms = {
        "treble": ("E", 4),
        "bass": ("G", 2),
        "alto": ("F", 3),
    }
    bottom_step, bottom_octave = bottoms[clef]
    relative = (note.octave * 7 + STEP_TO_DIATONIC[note.step]) - (
        bottom_octave * 7 + STEP_TO_DIATONIC[bottom_step]
    )
    if 0 <= relative <= 8:
        if relative % 2 == 0:
            return f"line {relative // 2 + 1}"
        return f"space {relative // 2 + 1}"
    if relative < 0:
        distance = -relative
        if distance % 2 == 0:
            return f"{distance // 2} ledger line below"
        return "ledger space below"
    distance = relative - 8
    if distance % 2 == 0:
        return f"{distance // 2} ledger line above"
    return "ledger space above"


def score_to_musicxml(score: ScoreData) -> str:
    root = ET.Element("score-partwise", version="4.0")

    work = ET.SubElement(root, "work")
    ET.SubElement(work, "work-title").text = score.title

    identification = ET.SubElement(root, "identification")
    encoding = ET.SubElement(identification, "encoding")
    ET.SubElement(encoding, "software").text = "Clef Shift"

    part_list = ET.SubElement(root, "part-list")
    score_part = ET.SubElement(part_list, "score-part", id="P1")
    ET.SubElement(score_part, "part-name").text = "Cello" if score.to_clef == "bass" else "Converted Part"

    part = ET.SubElement(root, "part", id="P1")
    notes_per_measure = score.beats

    for measure_index in range(max(1, (len(score.notes) + notes_per_measure - 1) // notes_per_measure)):
        measure = ET.SubElement(part, "measure", number=str(measure_index + 1))
        if measure_index == 0:
            attributes = ET.SubElement(measure, "attributes")
            ET.SubElement(attributes, "divisions").text = str(score.divisions)
            key = ET.SubElement(attributes, "key")
            ET.SubElement(key, "fifths").text = "-1"
            time = ET.SubElement(attributes, "time")
            ET.SubElement(time, "beats").text = str(score.beats)
            ET.SubElement(time, "beat-type").text = str(score.beat_type)
            clef = ET.SubElement(attributes, "clef")
            ET.SubElement(clef, "sign").text = CLEF_DATA[score.to_clef]["sign"]
            ET.SubElement(clef, "line").text = str(CLEF_DATA[score.to_clef]["line"])

        chunk = score.notes[measure_index * notes_per_measure:(measure_index + 1) * notes_per_measure]
        for note_event in chunk:
            note = ET.SubElement(measure, "note")
            pitch = ET.SubElement(note, "pitch")
            ET.SubElement(pitch, "step").text = note_event.step
            if note_event.alter:
                ET.SubElement(pitch, "alter").text = str(note_event.alter)
            ET.SubElement(pitch, "octave").text = str(note_event.octave)
            ET.SubElement(note, "duration").text = str(note_event.duration)
            ET.SubElement(note, "type").text = note_event.note_type

        missing = notes_per_measure - len(chunk)
        for _ in range(max(0, missing)):
            rest = ET.SubElement(measure, "note")
            ET.SubElement(rest, "rest")
            ET.SubElement(rest, "duration").text = "1"
            ET.SubElement(rest, "type").text = "quarter"

    return ET.tostring(root, encoding="unicode", xml_declaration=True)


def write_musicxml(score: ScoreData, output_path: Path) -> Path:
    output_path.write_text(score_to_musicxml(score), encoding="utf-8")
    return output_path


# ---- Reading MusicXML produced by an OMR engine (e.g. Audiveris) ----

# MusicXML <alter> -> the accidental suffix used by the rest of the app.
ALTER_TO_ACC = {0: "", 1: "#", -1: "b", 2: "##", -2: "bb"}


def musicxml_to_tokens(xml_text: str) -> tuple[list[str], int | None]:
    """Parse MusicXML into pitch tokens (e.g. "Bb4") and key-signature fifths.

    The token accidental is the *sounding* accidental, because MusicXML's
    <alter> already folds in the key signature.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return [], None

    # Strip namespaces so plain tag lookups work regardless of the engine.
    for el in root.iter():
        if isinstance(el.tag, str) and "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]

    key_fifths: int | None = None
    fifths_el = root.find(".//attributes/key/fifths")
    if fifths_el is not None and (fifths_el.text or "").strip().lstrip("-").isdigit():
        key_fifths = int(fifths_el.text.strip())

    tokens: list[str] = []
    for note in root.iter("note"):
        if note.find("rest") is not None or note.find("chord") is not None:
            continue
        pitch = note.find("pitch")
        if pitch is None:
            continue
        step = (pitch.findtext("step") or "").strip().upper()
        octave = (pitch.findtext("octave") or "").strip()
        try:
            alter = int(float((pitch.findtext("alter") or "0").strip()))
        except ValueError:
            alter = 0
        if step not in "ABCDEFG" or not octave.lstrip("-").isdigit():
            continue
        tokens.append(f"{step}{ALTER_TO_ACC.get(alter, '')}{octave}")

    return tokens, key_fifths
