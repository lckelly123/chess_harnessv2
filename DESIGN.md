---
name: "Chess Harness v2"
description: "A black and purple analysis workbench for inspectable chess agents."
colors:
  background: "#0d0c10"
  sidebar: "#121016"
  surface: "#17151e"
  surface-raised: "#1e1b27"
  surface-hover: "#262131"
  field: "#111015"
  ink: "#f2eff8"
  ink-soft: "#b4adbf"
  muted: "#a49bb4"
  accent: "#b89afc"
  accent-solid: "#7950d5"
  accent-hover: "#8860df"
  accent-wash: "#2c2143"
  rule: "#35303f"
  rule-soft: "#292531"
  success: "#93d4b4"
  danger: "#f0a7b3"
  danger-wash: "#39222c"
  warning: "#dfc58d"
  white-square: "#bcb1ce"
  black-square: "#695783"
  focus: "#c9b0ff"
typography:
  headline:
    fontFamily: '"Archivo Variable", "Segoe UI", sans-serif'
    fontSize: "27px"
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: "-0.025em"
  title:
    fontFamily: '"Archivo Variable", "Segoe UI", sans-serif'
    fontSize: "15px"
    fontWeight: 600
    letterSpacing: "-0.025em"
  body:
    fontFamily: '"Archivo Variable", "Segoe UI", sans-serif'
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.75
  control:
    fontFamily: '"Archivo Variable", "Segoe UI", sans-serif'
    fontSize: "13px"
    fontWeight: 600
  label:
    fontFamily: '"Archivo Variable", "Segoe UI", sans-serif'
    fontSize: "11px"
    fontWeight: 400
  data:
    fontFamily: '"Cascadia Code", Consolas, monospace'
    fontSize: "11px"
    fontWeight: 400
    lineHeight: 1.5
rounded:
  badge: "5px"
  compact: "6px"
  icon: "7px"
  control: "8px"
  notice: "9px"
  surface: "14px"
spacing:
  micro: "4px"
  tight: "6px"
  compact: "8px"
  control: "12px"
  standard: "16px"
  inset: "18px"
  panel: "20px"
  generous: "24px"
components:
  button-primary:
    backgroundColor: "{colors.accent-solid}"
    textColor: "#fff"
    typography: "{typography.control}"
    rounded: "{rounded.control}"
    padding: "0 16px"
    height: "42px"
  button-primary-hover:
    backgroundColor: "{colors.accent-hover}"
  button-secondary:
    backgroundColor: "{colors.surface-raised}"
    textColor: "{colors.ink-soft}"
    typography: "{typography.control}"
    rounded: "{rounded.control}"
    padding: "0 16px"
    height: "42px"
  button-danger:
    backgroundColor: "{colors.danger-wash}"
    textColor: "{colors.danger}"
    rounded: "{rounded.compact}"
    padding: "0 8px"
    height: "30px"
  field:
    backgroundColor: "{colors.field}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "0 12px"
    height: "42px"
  navigation-item:
    textColor: "{colors.ink-soft}"
    rounded: "{rounded.control}"
    padding: "0 12px"
    height: "44px"
  panel:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.surface}"
  status-running:
    backgroundColor: "#1c332b"
    textColor: "{colors.success}"
    rounded: "{rounded.badge}"
    padding: "4px 8px"
  trace-selection:
    backgroundColor: "{colors.accent-wash}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
---

# Design System: Chess Harness v2

## Overview

**Creative North Star: "The Analysis Workbench"**

Near-black graphite surfaces and violet selection give chess research a calm, concentrated workspace. The user specified black and purple; the analysis-workbench composition was selected within the delegated redesign. Archivo supplies crisp headings and readable evidence, while the lavender board carries the largest continuous color field.

Restrained containers, one-pixel divisions, and explicit state support sustained inspection. Dense records sit beside generous explanation text. The board, selected ply, and recorded decision remain connected; setup and secondary metadata unfold when needed.

**Key Characteristics:**

- Near-black surfaces with violet actions and selections
- Lavender board squares with outlined move endpoints
- Archivo interface text with monospace identifiers
- Flat tonal layers and quiet one-pixel divisions
- Synchronized position, selected explanation, and chronology

## Colors

Black and violet form the identity; mint, rose, and amber have specific status meanings. The frontmatter preserves the CSS source values.

### Primary

- **Violet Signal** (`accent`): icons, selected metadata, and proposed-move notation.
- **Action Violet** (`accent-solid`) and **Raised Violet** (`accent-hover`): primary commands, playback, and their hover state.
- **Violet Wash** (`accent-wash`): selected navigation, active ply groups, and selected harnesses.
- **Focus Lavender** (`focus`): shared keyboard outline.

### Secondary

- **Success Mint** (`success`): running status, return-to-live context, and positional completion.
- **Error Rose** (`danger`) on **Rose Wash** (`danger-wash`): failures and the stop action.
- **Queue Amber** (`warning`): queued status.

### Tertiary

- **Light Lavender Square** (`white-square`) and **Deep Lavender Square** (`black-square`): alternating board fields. Endpoint outlines adjust contrast against each square color.

### Neutral

- **Near Black** (`background`) and **Sidebar Graphite** (`sidebar`): workspace and persistent navigation.
- **Graphite Surface** (`surface`), **Raised Graphite** (`surface-raised`), and **Hover Graphite** (`surface-hover`): panels, inset controls, and feedback.
- **Recessed Field** (`field`): inputs and search.
- **Pale Ink** (`ink`), **Soft Ink** (`ink-soft`), and **Muted Lavender** (`muted`): primary content, supporting copy, and metadata.
- **Graphite Rule** (`rule`) and **Quiet Rule** (`rule-soft`): container outlines and internal divisions.

**The Selection Rule.** Violet identifies the action or evidence currently in focus; semantic statuses retain their own text and color.

## Typography

**Display Font:** Archivo Variable (with Segoe UI and sans-serif fallback)
**Body Font:** Archivo Variable (with Segoe UI and sans-serif fallback)
**Label/Mono Font:** Cascadia Code (with Consolas and monospace fallback)

**Character:** One locally bundled variable family connects navigation, controls, and explanations. Moderate heading weights and sentence case keep the workspace quiet; monospace is reserved for identifiers, versions, and machine notation.

### Hierarchy

- **Headline** (600, 27px, 1.2): workspace titles; responsive sizes step to 25px, 23px, and 22px.
- **Title** (600, 15px): recurring section headings. Larger panel headings use 17–19px; selected-move summaries use 18px with 1.35 line height.
- **Body** (400, 14px, 1.75): explanations and phase reports, bounded to 70–75ch where space permits. Short operational copy usually uses 12–13px.
- **Control** (600, 13px): primary and secondary actions; navigation uses the same size at weight 500.
- **Label** (400, 11px): supporting metadata and field context. Counts and replay positions use tabular numerals.
- **Data** (400, 11px, 1.5): version strings and saved-position metadata; secondary record identifiers can use 10px.

**The Evidence Hierarchy Rule.** Give explanations more reading space than metadata, and keep identifiers visually subordinate to the decision they describe.

## Layout

The shell has a sticky full-height navigation column (208px; 188px below 1250px) and a flexible main region capped at 1576px. Desktop content uses 28px outer padding, 16–24px region gaps, and tighter 4–12px spacing inside controls. Panel insets generally fall between 16px and 22px.

The Match desk pairs position and replay with selected explanation and chronology. The board is bounded by available width, viewport height, and a 650px desktop maximum. The trace scrolls independently. Match library and Positional testing place their index beside the main content when space permits.

At 1250px, columns compact and the positional index becomes horizontal. At 1000px, navigation becomes a horizontal header. At 760px, match panels stack, indexes scroll horizontally, and positional controls follow the board. At 480px, setup and library records become single-column and replay places its range on a separate line. The 1700px breakpoint gives the board column additional room.

**The Adjacency Rule.** Keep the inspected position and its explanation adjacent when width permits; on narrow screens, place explanation immediately after the board and replay controls.

## Elevation & Depth

Ordinary panels, navigation, buttons, and fields use no box shadows. Graphite tones, recessed fields, and one-pixel borders create depth. Chess pieces alone carry small SVG drop shadows for silhouette separation; these are not a surface-elevation scale.

**The Tonal Depth Rule.** Separate interface regions with surface tone and rules before introducing any new elevation effect.

State changes use color transitions (160ms, ease-out). Selected explanation content enters over 180ms with a 3px movement; loading indicators rotate over 1s. Reduced-motion preference disables animations and transitions.

## Shapes

Main containers use moderately rounded corners (14px), controls use 8px, and compact buttons and disclosures use 6–7px. Status labels and the board boundary use 5px corners. Board cells remain square; circular trace markers distinguish events. The shared keyboard outline is 2px with a 3px offset.

## Components

### Buttons

Compact and explicit, with an SVG icon when it clarifies the action.

- **Primary:** violet, white text, 42px minimum height, and 16px horizontal padding.
- **Secondary:** raised graphite with a graphite border; hover lifts to the hover surface.
- **Danger:** rose wash, rose text, and a restrained outline; stop is a compact 30px control.
- **Hover / Focus:** brief color feedback and the common lavender outline. Disabled controls retain their structure at 0.48 opacity.

### Chips

Rectangular status badges use 5px corners and 4px by 8px padding. Running is mint, completed match status is violet, failed is rose, and queued is amber. Status words stay visible; positional completion also includes an icon.

### Cards / Containers

Graphite panels use 14px corners, one-pixel borders, and no box shadow. Headers and bodies have separate insets so dividers span the panel. Lists use quiet row separators.

### Inputs / Fields

Recessed fields use graphite outlines, 8px corners, 42px height, and explicit labels. Search pairs an inline SVG icon with its field and adds a violet border on focus-within. Errors stay near the affected action.

### Navigation

Match desk, Match library, and Positional testing share one visual world. Items pair SVG icons with sentence-case labels; the current destination receives violet wash, lavender text, a border, and an accessibility state. The desktop rail becomes a horizontal strip. Model controls remain in the shared shell.

### Selected Move and Trace

The selected-ply inspector shows the recorded summary and explanation above chronology. Disclosures expose full metadata and other events at that ply. The timeline groups events by ply with Moves and All events filters. Selecting a row synchronizes position and explanation; a violet wash and the word “Selected” identify the active group. Full-event disclosures retain timestamp, player, ply, phase, status, stable event ID, and detail.

### Board and Replay

Lavender squares, SVG pieces, and contrasting endpoint outlines anchor the position. Pieces use traditional silhouettes, curved tiered bases, and open details that remain readable on small boards. Ivory white pieces use a dark outline; graphite black pieces use a lavender outline and lighter internal details. Each SVG occupies 88% of its square, with shared proportions across both colors. Replay combines neutral icon buttons, violet playback, a circular range thumb, and tabular counts. Flipping changes perspective while the selected ply continues to drive analysis.

### Setup, Library, and Positional Testing

Match setup expands from New match and opens automatically when no match is selected. Library records separate opening from folder assignment and disclose version identifiers. Positional testing uses saved-position rows and stacked harness radio choices; the selected choice reveals its description. Results emphasize violet move notation, justification, and phase reports. Route details and available harnesses belong in the surface brief.

## Do's and Don'ts

### Do:

- **Do** use graphite tones and one-pixel rules to separate regions.
- **Do** use violet consistently for actions, selection, and inspected evidence.
- **Do** keep board, replay position, selected explanation, and trace synchronized.
- **Do** pair status colors with words and preserve visible keyboard focus.
- **Do** disclose secondary metadata without removing access to the complete record.
- **Do** respect reduced motion and preserve readable content order on narrow screens.

### Don't:

- **Don't** reintroduce the superseded cream, tournament-green, and rust identity.
- **Don't** turn routine panels into elevated cards or add ornamental gradients and textures.
- **Don't** promote small metadata styling into the main reading text.
- **Don't** imply human move controls or frontend-authored decisions on the spectator board.
