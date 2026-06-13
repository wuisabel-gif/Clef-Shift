#!/usr/bin/env python3
from __future__ import annotations

import json
import mimetypes
import os
import re
import subprocess
import tempfile
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from omr_pipeline import analyze_image
from score_pipeline import build_score_data, score_to_musicxml, staff_position


ROOT = Path(__file__).resolve().parent
NOTE_PATTERN = re.compile(r"\b([A-Ga-g])([#b]?)(-?\d+)\b")


def normalize_note_tokens(text: str) -> list[str]:
    results: list[str] = []
    seen: set[str] = set()
    for letter, accidental, octave in NOTE_PATTERN.findall(text):
        token = f"{letter.upper()}{accidental}{octave}"
        if token not in seen:
            seen.add(token)
            results.append(token)
    return results


def run_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        cwd=ROOT,
    )


def rasterize_pdf(pdf_path: Path, output_path: Path) -> tuple[bool, str]:
    result = run_command([
        "gs",
        "-sDEVICE=png16m",
        "-dNOPAUSE",
        "-dBATCH",
        "-dSAFER",
        "-r200",
        "-dFirstPage=1",
        "-dLastPage=1",
        f"-sOutputFile={output_path}",
        str(pdf_path),
    ])
    if result.returncode != 0:
        return False, result.stderr.strip() or "Ghostscript failed"
    return True, ""


def ocr_file(file_path: Path) -> tuple[str, str]:
    result = run_command([
        "tesseract",
        str(file_path),
        "stdout",
        "--psm",
        "6",
    ])
    raw_text = result.stdout.strip()
    if result.returncode != 0 and not raw_text:
        return "", result.stderr.strip() or "Tesseract failed"
    return raw_text, result.stderr.strip()


class ClefShiftHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def do_POST(self) -> None:
        if self.path == "/api/score":
            self.handle_score_request()
            return

        if self.path != "/api/ocr":
            self.send_error(HTTPStatus.NOT_FOUND, "Unknown endpoint")
            return

        content_type = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in content_type:
            self.respond_json({"error": "Expected multipart form upload"}, status=HTTPStatus.BAD_REQUEST)
            return

        boundary_token = "boundary="
        if boundary_token not in content_type:
            self.respond_json({"error": "Missing multipart boundary"}, status=HTTPStatus.BAD_REQUEST)
            return

        boundary = content_type.split(boundary_token, 1)[1].encode()
        content_length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(content_length)

        parts = body.split(b"--" + boundary)
        upload_bytes = None
        upload_name = "upload.bin"
        source_clef = "treble"

        for part in parts:
            if b'name="source_clef"' in part:
                _header_blob, _, data = part.partition(b"\r\n\r\n")
                if data:
                    source_clef = data.rstrip(b"\r\n-").decode("utf-8", errors="ignore").strip() or "treble"
                continue
            if b'name="file"' not in part:
                continue
            header_blob, _, data = part.partition(b"\r\n\r\n")
            if not data:
                continue
            filename_match = re.search(br'filename="([^"]+)"', header_blob)
            if filename_match:
                upload_name = os.path.basename(filename_match.group(1).decode("utf-8", errors="ignore")) or upload_name
            upload_bytes = data.rstrip(b"\r\n-")
            break

        if not upload_bytes:
            self.respond_json({"error": "No file field found"}, status=HTTPStatus.BAD_REQUEST)
            return

        with tempfile.TemporaryDirectory(prefix="clef_shift_ocr_") as temp_dir:
            temp_path = Path(temp_dir)
            suffix = Path(upload_name).suffix.lower() or mimetypes.guess_extension(self.headers.get("Content-Type", "")) or ""
            source_path = temp_path / f"source{suffix}"
            source_path.write_bytes(upload_bytes)

            ocr_target = source_path
            mode = "image"
            warning = ""

            if suffix == ".pdf":
                rendered_path = temp_path / "page1.png"
                ok, warning = rasterize_pdf(source_path, rendered_path)
                if not ok:
                    self.respond_json({"error": warning}, status=HTTPStatus.BAD_REQUEST)
                    return
                ocr_target = rendered_path
                mode = "pdf"

            # Notes are read from the NOTATION by the OMR detector. OCR is used
            # only to surface incidental text (title, tempo, markings) and is
            # never the primary note source -- see the project handoff.
            raw_text, stderr_text = ocr_file(ocr_target)

            debug_dir = ROOT / "debug"
            result = analyze_image(ocr_target, source_clef, debug=True, debug_dir=debug_dir)

            notes = result.notes
            detection_mode = "music-notation" if result.success else "none"

            # Honest fallback: only when NO staff was found at all (e.g. a photo
            # of typed note names) do we offer note-like tokens parsed from OCR,
            # and we label them clearly so the UI does not present them as
            # notation that was read from a staff.
            if not notes and result.staff_count == 0:
                ocr_notes = normalize_note_tokens(raw_text)
                if ocr_notes:
                    notes = ocr_notes
                    detection_mode = "text-ocr-fallback"

            if detection_mode == "text-ocr-fallback":
                message = (
                    "No staff notation was found. The note names below were read "
                    "from text in the image, not from musical notation."
                )
            else:
                message = result.reason

            payload = {
                "file_name": upload_name,
                "ocr_mode": mode,
                "raw_text": raw_text,
                "notes": notes,
                "detection_mode": detection_mode,
                "detection_success": result.success,
                "staff_count": result.staff_count,
                "note_count": result.note_count,
                "spacing": round(result.spacing, 2),
                "debug_images": [os.path.relpath(p, ROOT) for p in result.debug_images],
                "warning": warning or stderr_text,
                "message": message,
            }
            self.respond_json(payload)

    def handle_score_request(self) -> None:
        content_length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(content_length)
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except json.JSONDecodeError:
            self.respond_json({"error": "Expected JSON body"}, status=HTTPStatus.BAD_REQUEST)
            return

        notes_text = str(payload.get("notes", "")).strip()
        from_clef = str(payload.get("from_clef", "treble")).strip() or "treble"
        to_clef = str(payload.get("to_clef", "bass")).strip() or "bass"
        title = str(payload.get("title", "Clef Shift Output")).strip() or "Clef Shift Output"

        score = build_score_data(notes_text, from_clef, to_clef, title)
        musicxml = score_to_musicxml(score)

        self.respond_json({
            "title": score.title,
            "from_clef": score.from_clef,
            "to_clef": score.to_clef,
            "note_count": len(score.notes),
            "notes": [note.token for note in score.notes],
            "positions": [staff_position(note, score.to_clef) for note in score.notes],
            "musicxml": musicxml,
            "message": "Generated MusicXML from structured score data" if score.notes else "No notes available for MusicXML generation",
        })

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def respond_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def main() -> None:
    host = "127.0.0.1"
    port = 8000
    server = ThreadingHTTPServer((host, port), ClefShiftHandler)
    print(f"Clef Shift server running at http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
