from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
from PIL import Image


BOTTOM_DIATONIC = {
    "treble": ("E", 4),
    "bass": ("G", 2),
    "alto": ("F", 3),
}
STEP_NAMES = ["C", "D", "E", "F", "G", "A", "B"]
STEP_TO_INDEX = {step: idx for idx, step in enumerate(STEP_NAMES)}


@dataclass
class StaffGroup:
    lines: list[float]
    spacing: float


@dataclass
class NoteCandidate:
    x: float
    y: float
    staff_index: int
    token: str


def load_binary_image(image_path: Path) -> np.ndarray:
    image = Image.open(image_path).convert("L")
    target_width = 1800
    if image.width < target_width:
        scale = target_width / image.width
        image = image.resize((int(image.width * scale), int(image.height * scale)), Image.Resampling.LANCZOS)
    gray = np.array(image, dtype=np.uint8)
    threshold = max(110, int(np.percentile(gray, 42)))
    binary = gray < threshold
    return binary


def group_consecutive(rows: Iterable[int]) -> list[list[int]]:
    rows = list(rows)
    if not rows:
      return []
    groups: list[list[int]] = [[rows[0]]]
    for row in rows[1:]:
        if row == groups[-1][-1] + 1:
            groups[-1].append(row)
        else:
            groups.append([row])
    return groups


def detect_staff_groups(binary: np.ndarray) -> list[StaffGroup]:
    row_strength = binary.mean(axis=1)
    smoothed = np.convolve(row_strength, np.ones(5) / 5.0, mode="same")
    lower = max(0.07, float(np.percentile(smoothed, 85)))
    upper = min(0.55, float(np.percentile(smoothed, 98)))
    candidate_rows = np.where((smoothed >= lower) & (smoothed <= upper))[0]
    row_groups = group_consecutive(candidate_rows)
    line_centers = [float(sum(group) / len(group)) for group in row_groups if 1 <= len(group) <= 8]
    if len(line_centers) < 5:
        return []

    diffs = np.diff(line_centers)
    near_diffs = [diff for diff in diffs if 6 <= diff <= 42]
    spacing = float(np.median(near_diffs)) if near_diffs else 12.0
    tolerance = max(3.0, spacing * 0.55)

    staffs: list[StaffGroup] = []
    i = 0
    while i <= len(line_centers) - 5:
        candidate = line_centers[i:i + 5]
        candidate_diffs = np.diff(candidate)
        if all(abs(diff - spacing) <= tolerance for diff in candidate_diffs):
            staffs.append(StaffGroup(lines=candidate, spacing=float(sum(candidate_diffs) / len(candidate_diffs))))
            i += 5
        else:
            i += 1
    return staffs


def remove_staff_lines(binary: np.ndarray, staffs: list[StaffGroup]) -> np.ndarray:
    result = binary.copy()
    for staff in staffs:
        for line in staff.lines:
            row = int(round(line))
            half = max(1, int(round(staff.spacing * 0.10)))
            top = max(0, row - half)
            bottom = min(result.shape[0], row + half + 1)
            result[top:bottom, :] = False
    return result


def connected_components(binary: np.ndarray) -> list[tuple[int, int, int, int, list[tuple[int, int]]]]:
    height, width = binary.shape
    visited = np.zeros((height, width), dtype=bool)
    components: list[tuple[int, int, int, int, list[tuple[int, int]]]] = []
    black_positions = np.argwhere(binary)

    for y, x in black_positions:
        if visited[y, x]:
            continue
        stack = [(int(y), int(x))]
        visited[y, x] = True
        pixels: list[tuple[int, int]] = []
        min_y = max_y = int(y)
        min_x = max_x = int(x)

        while stack:
            cy, cx = stack.pop()
            pixels.append((cy, cx))
            min_y = min(min_y, cy)
            max_y = max(max_y, cy)
            min_x = min(min_x, cx)
            max_x = max(max_x, cx)

            for ny in range(max(0, cy - 1), min(height, cy + 2)):
                for nx in range(max(0, cx - 1), min(width, cx + 2)):
                    if not visited[ny, nx] and binary[ny, nx]:
                        visited[ny, nx] = True
                        stack.append((ny, nx))

        components.append((min_y, min_x, max_y, max_x, pixels))
    return components


def estimate_note_center(component: tuple[int, int, int, int, list[tuple[int, int]]], binary: np.ndarray, spacing: float) -> tuple[float, float]:
    min_y, min_x, max_y, max_x, _pixels = component
    box = binary[min_y:max_y + 1, min_x:max_x + 1]
    window_h = max(4, int(round(spacing * 1.2)))
    window_w = max(5, int(round(spacing * 1.6)))
    integral = box.astype(np.int32).cumsum(axis=0).cumsum(axis=1)

    def rect_sum(y0: int, x0: int, y1: int, x1: int) -> int:
        total = integral[y1, x1]
        if y0 > 0:
            total -= integral[y0 - 1, x1]
        if x0 > 0:
            total -= integral[y1, x0 - 1]
        if y0 > 0 and x0 > 0:
            total += integral[y0 - 1, x0 - 1]
        return int(total)

    best_score = -1
    best_center = ((min_y + max_y) / 2, (min_x + max_x) / 2)

    max_scan_y = max(0, box.shape[0] - window_h)
    max_scan_x = max(0, box.shape[1] - window_w)
    for y in range(0, max_scan_y + 1):
        for x in range(0, max_scan_x + 1):
            score = rect_sum(y, x, min(box.shape[0] - 1, y + window_h - 1), min(box.shape[1] - 1, x + window_w - 1))
            if score > best_score:
                best_score = score
                best_center = (min_y + y + window_h / 2, min_x + x + window_w / 2)
    return best_center


def note_token_from_y(y: float, staff: StaffGroup, source_clef: str) -> str:
    bottom_step, bottom_octave = BOTTOM_DIATONIC[source_clef]
    bottom_index = bottom_octave * 7 + STEP_TO_INDEX[bottom_step]
    relative = round((staff.lines[-1] - y) / (staff.spacing / 2))
    diatonic_index = bottom_index + relative
    octave, step_index = divmod(diatonic_index, 7)
    return f"{STEP_NAMES[step_index]}{octave}"


def smooth_signal(signal: np.ndarray, window: int) -> np.ndarray:
    window = max(1, int(window))
    kernel = np.ones(window, dtype=np.float32) / float(window)
    return np.convolve(signal.astype(np.float32), kernel, mode="same")


def find_peak_ranges(signal: np.ndarray, threshold: float) -> list[tuple[int, int]]:
    indices = np.where(signal > threshold)[0]
    groups = group_consecutive(indices)
    return [(group[0], group[-1]) for group in groups]


def score_note_window(binary: np.ndarray, center_x: float, center_y: float, spacing: float) -> float:
    half_h = max(4, int(round(spacing * 0.52)))
    half_w = max(5, int(round(spacing * 0.72)))
    y0 = max(0, int(round(center_y)) - half_h)
    y1 = min(binary.shape[0], int(round(center_y)) + half_h + 1)
    x0 = max(0, int(round(center_x)) - half_w)
    x1 = min(binary.shape[1], int(round(center_x)) + half_w + 1)
    if y0 >= y1 or x0 >= x1:
        return 0.0

    window = binary[y0:y1, x0:x1]
    ink = float(window.sum())
    fill_ratio = ink / float(window.size)
    if fill_ratio < 0.10 or fill_ratio > 0.75:
        return 0.0

    # Favor compact elliptical blobs over broad noisy windows.
    return ink * (1.0 - abs(fill_ratio - 0.34))


def detect_notes_in_staff(binary: np.ndarray, staff: StaffGroup, staff_index: int, source_clef: str) -> list[NoteCandidate]:
    top_bound = max(0, int(round(staff.lines[0] - staff.spacing * 3.0)))
    bottom_bound = min(binary.shape[0], int(round(staff.lines[-1] + staff.spacing * 3.0)))
    left_bound = 120
    right_bound = max(left_bound + 1, binary.shape[1] - 20)
    crop = binary[top_bound:bottom_bound, left_bound:right_bound]
    if crop.size == 0:
        return []

    column_strength = crop.mean(axis=0)
    smoothed = smooth_signal(column_strength, max(3, int(round(staff.spacing * 0.9))))
    threshold = max(float(smoothed.mean() + smoothed.std() * 0.55), float(np.percentile(smoothed, 72)))
    peak_ranges = find_peak_ranges(smoothed, threshold)

    results: list[NoteCandidate] = []
    for start, end in peak_ranges:
        width = end - start + 1
        if width < max(4, int(round(staff.spacing * 0.30))) or width > max(24, int(round(staff.spacing * 2.3))):
            continue

        center_x = left_bound + (start + end) / 2.0
        best_score = 0.0
        best_y = None

        for relative_step in range(-6, 16):
            candidate_y = staff.lines[-1] - relative_step * (staff.spacing / 2.0)
            score = score_note_window(binary, center_x, candidate_y, staff.spacing)
            if score > best_score:
                best_score = score
                best_y = candidate_y

        if best_y is None:
            continue
        if best_score < max(10.0, staff.spacing * staff.spacing * 0.22):
            continue

        token = note_token_from_y(best_y, staff, source_clef)
        results.append(NoteCandidate(x=center_x, y=best_y, staff_index=staff_index, token=token))

    deduped: list[NoteCandidate] = []
    for candidate in results:
        if deduped and abs(candidate.x - deduped[-1].x) < max(14, staff.spacing * 0.75):
            continue
        deduped.append(candidate)
    return deduped


def detect_notes(image_path: Path, source_clef: str) -> list[str]:
    binary = load_binary_image(image_path)
    staffs = detect_staff_groups(binary)
    if not staffs:
        return []

    without_lines = remove_staff_lines(binary, staffs)
    candidates: list[NoteCandidate] = []

    for staff_index, staff in enumerate(staffs):
        candidates.extend(detect_notes_in_staff(without_lines, staff, staff_index, source_clef))

    candidates.sort(key=lambda candidate: (candidate.staff_index, candidate.x))

    deduped: list[NoteCandidate] = []
    for candidate in candidates:
        if deduped:
            last = deduped[-1]
            if candidate.staff_index == last.staff_index and abs(candidate.x - last.x) < 20:
                continue
        deduped.append(candidate)

    return [candidate.token for candidate in deduped]
