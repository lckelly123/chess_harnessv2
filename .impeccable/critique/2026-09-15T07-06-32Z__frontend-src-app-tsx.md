---
target: frontend design review
total_score: 24
max_score: 40
na_heuristics: 
p0_count: 0
p1_count: 2
timestamp: 2026-09-15T07-06-32Z
slug: frontend-src-app-tsx
---
Method: dual-agent (A: /root/design_review · B: /root/implementation_review)

# Frontend design review

## Design verdict

**Keep the paper-and-green identity. Rebuild the hierarchy around the board, selected move, and its explanation.**

The frontend feels authored for a chess research tool. Its main weakness is composition: the large board, persistent setup form, tiny metadata, and expanded event feed make investigation harder than it should be.

Reviewed the running match desk, history, and positional testing at laptop and phone widths. These are design-review judgments, not a full usability certification.

## What works

- **Distinctive visual language:** tournament green, cream surfaces, ruled rows, and rust move markers work together.
- **Readable chess graphics:** clear piece silhouettes, coordinates, and changed-square outlines.
- **Useful research context:** versioned players, saved records, folders, and replay already support the intended workflow.

## Priority improvements

### 1. [P1] Fit the complete working view on screen

At 1280 × 720, the board measures 720 × 720 and replay controls begin around y=1134. Users must scroll away from part of the position to operate it. At phone width, the board starts around y=730 because setup and status occupy most of the first screen.

**Design recommendation:** collapse New match into an expandable control when a record is open; compact the match summary; size the board using available height as well as width. Keep the complete board, transport, and selected explanation together on desktop.

In positional testing, place the harness chooser and Run action beside the board. On phones, lead with the selected match and board, then reveal setup when requested.

Source: [layout and board sizing](C:/Repos/chess_harness_v2/chess_harnessv2/frontend/src/styles.css:1156). Suggested command: `$impeccable layout`.

### 2. [P1] Make the trace explain the selected move

The initial record opens at **ply 35**, while the trace starts at **ply 0**. Its 72 event buttons occupy roughly 8,861px of scrollable content. The relevant explanation is buried.

**Design recommendation:** place a selected-move inspector at the top: move notation, player, phase, and justification. Below it, show a compact chronology with long explanations expandable. Follow the selected move automatically, with an explicit control to pause following while browsing older events.

Group routine phase entries by turn. Preserve complete source text in expanded detail.

Source: [TracePanel.tsx](C:/Repos/chess_harness_v2/chess_harnessv2/frontend/src/components/TracePanel.tsx:26). Suggested command: `$impeccable distill`.

### 3. [P2] Make the typography comfortable and the versions legible

Much of the evidence uses 9–12px text. Harness selectors truncate versions, and history squeezes player names and identifiers onto the same line.

**Design recommendation:** use approximately **14px for reading, 12px for metadata, and 11px only for exceptional micro-labels**. Keep Archivo and the existing body family. Use sentence case for ordinary controls and reserve uppercase for short labels.

Give player names a clear first line and versions a quieter second line. Provide full identifiers through keyboard-accessible disclosure and copy. Selected harnesses should have a readable version confirmation outside the truncated dropdown.

Source: [trace typography](C:/Repos/chess_harness_v2/chess_harnessv2/frontend/src/styles.css:1712) and [HistoryList.tsx](C:/Repos/chess_harness_v2/chess_harnessv2/frontend/src/components/HistoryList.tsx:65). Suggested command: `$impeccable typeset`.

### 4. [P2] Give records a clearer browsing hierarchy

Record rows lead with opaque IDs, repeated versions, and an always-visible folder dropdown. Opening a record updates the board above the list. Switching to positional testing can preserve the previous scroll position and hide the new page heading.

**Design recommendation:** lead each row with the player pairing and outcome; place date and version details beneath; treat record ID as supporting, copyable metadata. Show the folder as a compact label with an explicit edit action.

Keep record browsing beside the inspector where space allows, or move focus and scroll to the opened record. Give each workspace an intentional entry position.

Source: [HistoryList.tsx](C:/Repos/chess_harness_v2/chess_harnessv2/frontend/src/components/HistoryList.tsx:59) and [workspace navigation](C:/Repos/chess_harness_v2/chess_harnessv2/frontend/src/App.tsx:264). Suggested commands: `$impeccable layout`, `$impeccable polish`.

### 5. [P3] Lighten the visual finish

The broad brown board surround, strong shadow, and frequent borders make the screen feel heavier than the underlying ledger concept needs.

**Design recommendation:** narrow the board surround, soften its shadow, and use lighter internal dividers. Separate groups with spacing before adding another box. Keep dark green for primary actions and rust for the selected move or intervention.

The three positional harness choices should form three deliberate rows instead of a two-column grid with an empty fourth cell. Reduce the oversized empty-position panel until a position is selected.

Source: [board surround](C:/Repos/chess_harness_v2/chess_harnessv2/frontend/src/styles.css:1401). Suggested command: `$impeccable polish`.

## Design health

All ten heuristics apply. Scores are expert judgments on a 0–4 scale.

| Heuristic | Score | Main issue |
|---|---:|---|
| System status | 2 | Position and visible trace disagree |
| Familiar language | 3 | Some raw phase terminology |
| User control | 3 | Workspace scroll does not reset appropriately |
| Consistency | 3 | “Stopped” and “aborted” diverge |
| Error prevention | 3 | Constrained choices and disabled pending actions help |
| Recognition | 2 | Versions truncate; current evidence is buried |
| Efficiency | 2 | Limited trace navigation and replay accelerators |
| Visual simplicity | 2 | Setup, board, and expanded prose compete |
| Error recovery | 2 | General errors depend on broad Reload |
| Contextual help | 2 | Explanations exist; phase/help links are limited |
| **Total** | **24/40** | **Acceptable; substantial improvements needed** |

## Cognitive load and user impact

The most costly extra work is remembering the position while scrolling to controls or searching for its explanation. The initial impression is calm and credible; confidence drops during investigation.

- **Power user:** long trace scrolling and clipped versions slow comparison.
- **Low-vision or keyboard user:** tiny metadata and selection conveyed mainly through styling undermine otherwise useful labels and focus outlines.
- **First-time collaborator:** inconsistent status wording and hidden headings after navigation create uncertainty.

Long lists are appropriate here; grouping and progressive disclosure should make them manageable.

## Smaller improvements

- Unify stopped/aborted presentation into one clear terminal summary.
- Add explicit “to move” wording and accessible current-item state to selected trace rows.
- Add a page heading and correct trace list semantics.
- Give the runtime indicator a neutral appearance unless it reflects verified health.
- Add sighted tooltips to the already-labelled replay icons.

## Automated evidence

The Impeccable detector scanned `frontend/src` once and returned **0 findings** (`[]`); there were no rule locations or false positives. It did not flag the layout and interaction issues confirmed by browser inspection. No live overlay was injected because browser evaluation is read-only.

## Direction questions

1. Which should the next layout prioritize: **move analysis (recommended)**, **live viewing**, or **experiment comparison**?
2. Should it **refine the current ledger identity (recommended)** or **explore a different visual identity**?
