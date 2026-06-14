# Clef Shift — UI Spec

What you need to recreate the Clef Shift look: a warm "engraved sheet-music /
print-room" surface, made friendly and modern by a single rounded display font.
Everything lives in one self-contained `index.html` (inline `<style>`), served by
the local Python server so fonts load from `/fonts/`.

## 1. Type

One font for the whole UI: **ALK Rounded Nusx Med**, self-hosted.

```css
@font-face {
  font-family: "ALK Rounded Nusx Med";
  src: url("/fonts/alk-rounded-nusx-med-webfont.ttf") format("truetype");
  font-display: swap;
}
body { font-family: "ALK Rounded Nusx Med", "Avenir Next", "Segoe UI", system-ui, sans-serif; }
```

- **Everything** (title, labels, buttons, body, footer) uses this one family — no serif/sans pairing.
- **Exceptions, on purpose:**
  - the raw detected-notes dump (`.notes-box pre`) stays **monospace** so note tokens align;
  - text *inside the notation SVG* (clef glyph, accidentals) stays a serif (`Baskerville`) so the **music symbols render** — those are notation, not UI.
- Scale: `h1` `clamp(52px, 7vw, 84px)`, section titles ~26–30px, body ~15–17px, labels 11–12px uppercase with `letter-spacing: 0.08–0.14em`.
- Headings: `line-height` ~1.0, near-zero letter-spacing (the rounded font is wide; don't tighten it).

## 2. Color

Warm paper base, deep-teal accent, gold trim. Tokens (in `:root`):

```css
--bg: #f4ede0;          /* page background        */
--sidebar-bg: #eae0cd;  /* tinted control sidebar */
--paper: #fffdfa;       /* white work surface     */
--ink: #161f1d;         /* near-black text        */
--muted: #596764;       /* secondary text         */
--line: rgba(66,83,78,0.12);
--line-strong: rgba(49,68,63,0.22);
--accent: #1f5c53;      /* primary teal           */
--accent-dark: #123b35;
--accent-soft: #e3ede9;
--gold: #b88a3b;        /* seal / footer / trim   */
--shadow-sm: 0 4px 12px rgba(51,41,26,0.04);
--shadow:    0 20px 48px rgba(51,41,26,0.1);
```

- Page bg is a soft vertical gradient `#fbf7f0 → var(--bg)` with two faint radial tints (teal top-left, gold top-right).
- **Before/after split:** the left controls panel is `--sidebar-bg` (tinted), the right output panel is `--paper` (white). That contrast carries the layout.
- Accent (`--accent`) is for the one primary action and active states only — not decoration.

## 3. Layout

```
┌──────────────────────────── hero (paper, rounded 24px) ───────────────────────┐
│  [eyebrow chip]  Clef Shift            ……              ( 𝄞 → 𝄢 seal )         │
│  one-line lead                                                                 │
│  ── faint engraved staff-line flourish ──                                      │
└────────────────────────────────────────────────────────────────────────────────┘
┌── sidebar (380px, --sidebar-bg) ──┐ ┌──────── output panel (1fr, --paper) ──────┐
│ Upload  · dropzone                │ │ Clef Shift Output                          │
│ Source/Target clef · title · notes│ │   [ Original upload preview ]              │
│ [ Convert ] Download · PDF · Image │ │ Generated Output                           │
│ Clear · status box                │ │   caption pill · notation · result cards   │
└───────────────────────────────────┘ └────────────────────────────────────────────┘
                              footer: 𝄢  © …
```

- `shell`: `width: min(1240px, 100% - 40px)`, centered.
- `.app-grid`: `grid-template-columns: 380px 1fr; gap: 32px`. Collapses to one column at ≤960px.
- Radii: panels 24px, inner cards/inputs 12–16px. Generous padding (24–32px). Vary spacing for rhythm.

## 4. Components

- **Dropzone:** white, `2px dashed` teal, rounded; on hover/drag → accent border + `--accent-soft` fill.
- **Inputs / selects / textarea:** white (`--paper`), 1px line border, subtle `inset` shadow, 11–12px radius; focus = teal border + `0 0 0 3px` teal glow.
- **Button hierarchy (the important one):**
  - **Primary** `#convertButton`: solid teal gradient, white text, the only loud button.
  - **Secondary** downloads (MusicXML / Save PDF / Download Image): white, teal text, thin border.
  - **Ghost/destructive** Clear: transparent, muted text, hover tints red.
- **Status box:** soft card under the buttons. States: `.is-busy` (calm shimmer while reading/converting), `.is-warning` (amber + ⚠, for "limited fallback detection").
- **Notation block:** white card with a rounded **caption pill** (`TREBLE → BASS`, gold arrow) above an inline SVG staff; converted notes/clef/positions in small cards below.
- **"Converting…" overlay:** semi-opaque blurred cover over the output with a spinner + animated dots while a read/convert runs; the Convert button disables and reads "Converting…".

## 5. Motifs (what makes it feel like sheet music)

- **𝄞 → 𝄢 wax-seal medallion** in the hero — a round cream "stamp" with a gold ring.
- **Engraved staff-line flourish** under the hero text (faint repeating horizontal lines, masked to fade out).
- **Bass-clef 𝄢** mark in the footer, in gold.
- Caption "pill" tags in gold-tinted cream.

## 6. Motion

Subtle, state-driven, and reduced-motion safe:

- Panels fade-up on load (staggered, `cubic-bezier(0.16, 1, 0.3, 1)`).
- Notes "ink in" with a small staggered scale/opacity when a conversion renders.
- Status shimmer while busy; spinner while converting; gentle hover lifts on cards/buttons.
- Everything gated behind `@media (prefers-reduced-motion: no-preference)`, with static fallbacks otherwise.

## 7. Accessibility

- Body text ≥ 4.5:1 on its background; large/secondary text ≥ 3:1.
- State conveyed in **text**, not color alone (e.g., the "Limited fallback detection" notice).
- Full `prefers-reduced-motion` support.

---

**One-line summary:** warm paper + deep-teal/gold + a single rounded display font (ALK
Rounded Nusx Med), a tinted control sidebar against a white output canvas, light
engraving motifs (seal, staff flourish, clef), and quiet, purposeful motion.
