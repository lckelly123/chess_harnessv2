import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { TraceEvent } from "../api/contracts";
import { TracePanel } from "./TracePanel";

const move: TraceEvent = {
  id: "move-1",
  timestamp: "2026-09-21T10:00:00Z",
  ply: 1,
  player: "white",
  phase: "act",
  status: "complete",
  summary: "White harness played e4",
  detail: "Claims central space and opens the bishop’s diagonal.",
};

describe("TracePanel move inspection", () => {
  it("keeps the move explanation prominent when a terminal event follows at the same ply", () => {
    const terminal: TraceEvent = {
      ...move,
      id: "terminal-1",
      timestamp: "2026-09-21T10:00:01Z",
      player: "black",
      phase: "verify",
      status: "failed",
      summary: "Match failed",
      detail: "The following turn exceeded its time limit.",
    };
    const html = renderToStaticMarkup(<TracePanel events={[move, terminal]} activePly={1} onSelectPly={() => {}} />);
    const inspector = html.split('<section class="trace-timeline"')[0];

    expect(inspector).toContain(`<h3 class="inspector-summary">${move.summary}</h3>`);
    expect(inspector).toContain(move.detail);
    expect(inspector).toContain(terminal.summary);
    expect(inspector).toContain(terminal.detail);
    expect(inspector).toContain(terminal.id);
    expect(html).toContain('aria-current="step"');
    expect(html).toContain('<ol class="trace-list"');
  });

  it("inspects only the requested ply and explains a position with no public events", () => {
    const html = renderToStaticMarkup(<TracePanel events={[move]} activePly={0} onSelectPly={() => {}} />);
    const inspector = html.split('<section class="trace-timeline"')[0];

    expect(inspector).toContain("The starting position");
    expect(inspector).not.toContain(move.detail);
    expect(html).toContain(move.summary);
    expect(html).not.toContain('aria-current="step"');
  });
});
