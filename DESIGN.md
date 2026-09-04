---
name: "Chess Harness v2"
description: "A tournament arbiter's ledger for inspectable agent-versus-agent chess matches."
colors:
  desk-backdrop: "#d9dedb"
  ink: "#1c2723"
  ink-soft: "#53615b"
  paper: "#f5f1e7"
  paper-deep: "#e9e3d4"
  green: "#244c40"
  green-raised: "#316657"
  green-wash: "#dbe8df"
  rust: "#a34131"
  rust-deep: "#7e2f24"
  rule: "#a8aea7"
  rule-dark: "#68736d"
  white-square: "#e7dbc2"
  black-square: "#567769"
  focus: "#0a67a3"
typography:
  headline:
    fontFamily: '"Archivo Variable", "Arial Narrow", sans-serif'
    fontSize: "19px"
    fontWeight: 700
    lineHeight: 1.2
    letterSpacing: "-0.025em"
  title:
    fontFamily: '"Archivo Variable", "Arial Narrow", sans-serif'
    fontSize: "16px"
    fontWeight: 700
    letterSpacing: "-0.02em"
  body:
    fontFamily: '"Segoe UI Variable", "Aptos", "Helvetica Neue", Arial, sans-serif'
    fontSize: "13px"
    fontWeight: 400
    lineHeight: 1.45
  label:
    fontFamily: '"Archivo Variable", "Arial Narrow", sans-serif'
    fontSize: "11px"
    fontWeight: 800
    letterSpacing: "0.04em"
  data:
    fontFamily: 'ui-monospace, "Cascadia Mono", Consolas, monospace'
    fontSize: "10px"
    fontWeight: 800
    letterSpacing: "0.04em"
rounded:
  registration: "2px"
  board: "4px"
  control: "8px"
  surface: "12px"
  pill: "999px"
spacing:
  micro: "4px"
  compact: "8px"
  control: "12px"
  standard: "16px"
  panel: "18px"
  wide: "24px"
components:
  button-primary:
    backgroundColor: "{colors.green}"
    textColor: "#fffdf7"
    typography: "{typography.label}"
    rounded: "{rounded.control}"
    padding: "0 14px"
    height: "42px"
  button-primary-hover:
    backgroundColor: "{colors.green-raised}"
    textColor: "#fffdf7"
    typography: "{typography.label}"
    rounded: "{rounded.control}"
    padding: "0 14px"
    height: "42px"
  button-danger:
    backgroundColor: "#ead4cc"
    textColor: "{colors.rust-deep}"
    typography: "{typography.label}"
    rounded: "7px"
    padding: "0 9px"
    height: "32px"
  field:
    backgroundColor: "#fffdf7"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.control}"
    padding: "0 12px"
    height: "42px"
  ledger-surface:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    rounded: "{rounded.surface}"
    padding: "{spacing.standard}"
  status-running:
    backgroundColor: "#cae4d4"
    textColor: "#174434"
    typography: "{typography.data}"
    rounded: "{rounded.pill}"
    padding: "5px 9px"
  registration-mark:
    backgroundColor: "{colors.rust}"
    rounded: "{rounded.registration}"
    size: "14px"
  trace-active:
    backgroundColor: "{colors.green-wash}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    padding: "13px 15px"
---

# Design System: Chess Harness v2

## Overview

**Creative North Star: "The Arbiter's Ledger"**

The Arbiter's Ledger treats every position, notation, and causal trace as one signed record. Its visual world is calm but unmistakable: vellum sheets sit on a cool desk, graphite rules turn dense evidence into a readable register, tournament green establishes authority, and rust marks the exact place where attention or intervention is required.

The system is flat, compact, and documentary rather than game-like. Square board cells, ruled rows, tabular annotations, and restrained type create the feeling of a working tournament desk; tonal shifts carry hierarchy while rare registration marks keep the current ply visible across the record. It explicitly refuses the detached board-plus-generic-dashboard pattern.

**Key Characteristics:**

- Vellum surfaces on a cool neutral desk
- Tournament green authority with rust registration marks
- Graphite rules, square ledger cells, and compact tabular evidence
- Position, notation, and causal trace treated as one synchronized record
- Flat tonal layering with narrowly reserved shadows

## Colors

The palette feels archival and operational: warm papers and cool graphite neutrals support a restrained tournament green, while rust appears only where the record needs an unmistakable mark.

### Primary

- **Tournament Green** (`#244c40`): anchors the sticky header, primary controls, selection color, and authoritative metadata.
- **Raised Tournament Green** (`#316657`): provides the primary interactive hover state without changing the material character.
- **Tournament Wash** (`#dbe8df`): identifies active rows, the side to move, selected records, and low-emphasis hover feedback.

### Secondary

- **Rust Registration** (`#a34131`): marks changed squares, the replay diamond, active trace registration, and destructive hover states.
- **Deep Rust** (`#7e2f24`): carries destructive labels and current-move notation before activation.

### Tertiary

- **Light Ledger Square** (`#e7dbc2`): the board's warm light field.
- **Dark Ledger Square** (`#567769`): the board's muted green field.
- **Focus Blue** (`#0a67a3`): reserved for high-contrast keyboard focus outlines.

### Neutral

- **Desk Backdrop** (`#d9dedb`): the cool field behind the ledger sheets.
- **Graphite Ink** (`#1c2723`): primary copy, piece strokes, and decisive labels.
- **Muted Graphite** (`#53615b`): supporting descriptions and secondary facts.
- **Vellum** (`#f5f1e7`): the default ledger surface.
- **Deep Vellum** (`#e9e3d4`): recessed tracks and secondary paper regions.
- **Graphite Rule** (`#a8aea7`): ordinary card, row, and section rules.
- **Dark Graphite Rule** (`#68736d`): field outlines, markers, and stronger structural boundaries.

**The Registration Rule.** Rust is a locating device, not decoration: use it for the active move, an intervention, or a failed state, and keep routine actions green or neutral.

## Typography

**Display Font:** Archivo Variable (with Arial Narrow fallback)
**Body Font:** Segoe UI Variable (with Aptos, Helvetica Neue, Arial fallbacks)
**Label/Mono Font:** UI monospace (with Cascadia Mono and Consolas fallbacks)

**Character:** Archivo gives headings and controls the compact authority of printed tournament forms, while Segoe keeps sustained interface reading neutral and clear. Monospace type turns versions, plies, clocks, record ids, and event metadata into evidence that aligns cleanly.

### Hierarchy

- **Headline** (700, `19px`, `1.2`): section and match titles, tightened slightly to keep dense headers decisive.
- **Title** (700, `16px`): the compact brand title and other small identity-level headings.
- **Body** (400, `13px`, `1.45`): event summaries, field content, and operational explanatory copy; trace detail stays within roughly `64ch`.
- **Label** (800, `11px`, `0.04em`, uppercase): field labels, replay labels, and terse docket annotations.
- **Data** (800, `10px`, `0.04em`, tabular where numeric): record ids, versions, clocks, counts, phases, and plies.

**The Evidence Hierarchy Rule.** Prose explains; Archivo labels; monospace proves. Do not use decorative type to imitate chess culture.

## Layout

The shipped match desk uses a centered canvas capped at `1440px`, with `16px` gaps and ruled vellum regions. At wide widths, the current position and causal trace remain adjacent; below `900px` they stack in reading order, and below `620px` controls, player registers, replay transport, and record rows recompose for one-handed scanning. These measurements document this route's evidence-heavy composition, not a universal template for every future screen.

Spacing stays on a compact rhythm (`4px`, `8px`, `12px`, `16px`, `18px`, `24px`). Dense metadata remains close to the fact it qualifies, while larger gaps separate functional regions. Responsive changes preserve the narrative sequence—setup, status, position, trace, records—without shrinking the board into illegibility.

**The Adjacency Rule.** On investigative surfaces, keep the artifact under inspection and the evidence that explains it adjacent when space permits; when they stack, preserve their causal reading order.

## Elevation & Depth

The system is flat by default. Vellum, deep paper, green wash, board fields, and graphite rules create separation through tone and line rather than floating cards. Shadows are reserved for the sticky header (`0 10px 30px rgb(24 39 33 / 18%)`), the board (`0 16px 28px rgb(35 48 42 / 22%)`), and the live environment dot (`0 2px 8px rgb(151 196 164 / 55%)`).

### Shadow Vocabulary

- **Sticky Authority** (`0 10px 30px rgb(24 39 33 / 18%)`): keeps the tournament-green header legible as content moves beneath it.
- **Board Object** (`0 16px 28px rgb(35 48 42 / 22%)`): gives the physical board the sole substantial lift in the workspace.
- **Live Signal** (`0 2px 8px rgb(151 196 164 / 55%)`): a compact glow that communicates local live presence without coloring an entire region.

**The Flat-by-Default Rule.** Use tonal layering and graphite rules for ordinary hierarchy; do not add shadow to routine cards, rows, inputs, or buttons.

## Shapes

Ledger surfaces use gently clipped corners (`12px`) so the desk remains approachable, while controls use tighter corners (`8px`) and the board stays nearly square (`4px`). Registration marks are square (`2px`) and rotated into diamonds; board cells and ruled rows remain square-edged. Pill geometry (`999px`) belongs to status badges and scrollbar thumbs, not to general containers.

**The Registration Geometry Rule.** A rust diamond means “this exact point in the record”; keep that silhouette consistent across notation, replay, and trace.

## Components

Components should feel like compact instruments on an arbiter's desk: sturdy, legible, and visibly stateful without ornamental chrome.

### Buttons

- **Shape:** compact control corners (`8px`) with a minimum height of `42px`; the smaller stop action uses `7px` corners and a `32px` height.
- **Primary:** tournament-green field, bright vellum text, heavy Archivo label, and horizontal padding of `14px`.
- **Hover / Focus:** primary hover lifts tonally to raised green; all interactive controls receive a `3px` mixed-blue keyboard outline with `2px` offset.
- **Danger:** pale rust at rest with deep-rust copy, becoming solid rust with bright text on hover. Disabled controls remain structurally visible at reduced opacity.

### Chips

- **Style:** compact uppercase or tabular labels on semantic washes, with full pill rounding.
- **State:** running is green, completed is graphite, stopped or failed is rust, and queued is ochre; wording remains present so color never carries status alone.

### Cards / Containers

- **Corner Style:** vellum ledger surfaces use `12px` corners; internal rows remain ruled and square.
- **Background:** vellum for primary containers, deep vellum or green wash for recessed and active regions.
- **Shadow Strategy:** none at rest; follow the reserved shadow vocabulary above.
- **Border:** a `1px` graphite rule defines the container and its internal ledger divisions.
- **Internal Padding:** usually `16px` or `18px`, reduced to `13px`–`14px` on narrow screens.

### Inputs / Fields

- **Style:** bright paper field, dark graphite `1px` outline, `8px` corners, and a `42px` minimum height.
- **Focus:** the shared high-contrast blue outline appears outside the field without displacing layout.
- **Disabled:** retain the field silhouette and switch the cursor to unavailable; action-dependent disabled buttons use reduced opacity.

### Navigation

- **Style:** the sticky tournament-green header is the sole elevated navigation surface. The checker mark, compact Archivo wordmark, uppercase subtitle, and live environment indicator stay horizontally economical; narrow screens retain the dot while visually suppressing its label.

### Replay Registration

The replay system is the signature component. A rust diamond on the square track aligns the active ply with current notation, changed board squares, and the active trace row. Transport controls are square, the main play control is green-filled, and the numeric position remains tabular.

### Trace Ledger

Trace events are full-width ruled rows with a vertical chronology line. Completed markers are circular and quiet; the active marker becomes the same rust diamond used by replay and changed squares, while the row receives a green wash.

### History Record

History rows behave like ledger entries rather than cards. Record id, versions, timestamp, and result align in compact columns on desktop, then collapse to a readable stacked entry on mobile; selection uses green wash plus an underlined id.

## Do's and Don'ts

### Do:

- **Do** use paper and green washes to separate regions before adding elevation.
- **Do** keep version identifiers, plies, clocks, and event metadata tabular and compact.
- **Do** use rust to register the active move, destructive action, or failed state.
- **Do** preserve a visible focus outline and pair every status color with text.
- **Do** keep position, notation, and trace synchronized when a replay cursor is present.

### Don't:

- **Don't** turn the product into a generic card dashboard detached from the chess position.
- **Don't** add gradients, glass effects, ornamental textures, or casual game styling.
- **Don't** scatter shadows across routine surfaces; reserve them for the header, board, and live dot.
- **Don't** use rounded softness everywhere; preserve square cells, ruled rows, and compact controls.
- **Don't** infer human move controls or editable agent behavior from spectator data.
