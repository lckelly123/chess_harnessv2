import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { CodexTrainingChoice } from "./CodexTrainingChoice";

describe("Codex training choice", () => {
  it("explains how to connect an offline worker without requiring a local model", () => {
    const html = renderToStaticMarkup(<CodexTrainingChoice selected disabled={false} worker={null} onSelect={() => {}} />);
    expect(html).toContain("Codex (training)");
    expect(html).toContain("Windows worker offline");
    expect(html).toContain("start-codex-worker.ps1");
    expect(html).toContain('value="codex-training"');
    expect(html).not.toContain("disabled=");
  });

  it("identifies the configured teacher model and locks selection during a run", () => {
    const html = renderToStaticMarkup(<CodexTrainingChoice selected disabled worker={{
      configured: true, online: true, model: "teacher-fixture", reasoning_effort: "high", active_run_id: null,
    }} onSelect={() => {}} />);
    expect(html).toContain("teacher-fixture · high reasoning");
    expect(html).toContain("disabled=");
    expect(html).not.toContain("worker offline");
  });
});
