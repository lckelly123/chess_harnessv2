// Browser fixtures only: never starts Codex, a model, or a database run.
import assert from "node:assert/strict";
import { existsSync, mkdirSync } from "node:fs";
import { resolve } from "node:path";
import { chromium } from "playwright-core";

const executablePath = [process.env.CHROME_PATH,
  "C:/Program Files/Google/Chrome/Application/chrome.exe",
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
  "/usr/bin/chromium"].find((path) => path && existsSync(path));
assert.ok(executablePath, "A Chromium browser is required.");
const baseUrl = process.env.POSITION_UI_URL ?? "http://127.0.0.1:5173";
const directory = resolve("../.impeccable/review");
mkdirSync(directory, { recursive: true });
const harnesses = ["Baseline", "legacy", "chess_harness", "chess_charness_alt"].map((name, i) => ({
  id: i === 0 ? "baseline-direct-submit-langgraph-v1" : `agent-player-${i}-langgraph-v1`,
  name, version: "v1", summary: "Browser test fixture.",
}));
const position = {
  id: "11111111-1111-4111-8111-111111111111", name: "Middlegame · move 20",
  datasetVersion: "v1", split: "train", phase: "middlegame", positionType: "quiet",
  source: "lichess_game", sourceGameId: "0wtBizME", sourceUrl: "https://lichess.org/0wtBizME",
  opening: "Alekhine Defense: Exchange Variation", themes: [], puzzleRating: null,
  sideToMove: "white", moveCount: 38,
  position: { ply: 38, fen: "r1b1r1k1/pp3ppp/5q2/3p4/1P1P1B2/P2Q3P/5PP1/2R2RK1 w - - 1 20", san: "Qf6", player: "black", fromSquare: "d8", toSquare: "f6" },
};
const runId = "22222222-2222-4222-8222-222222222222";
const now = "2026-10-14T20:00:00Z";
const explanation = "The current input gives the legal moves. I will inspect the queen before updating its safety assessment.";
const response = '<running_thoughts>\nVulnerabilities: Queen safety is unverified.\n\nOpportunities: Not assessed.\n\nSynthesis: Pending inspections.\n</running_thoughts>\n\n<agent_tool_calls>\n[{"tool":"inspect_square","arguments":{"board":"canonical","square":"d3"}}]\n</agent_tool_calls>';
const browser = await chromium.launch({ executablePath, headless: true });
try {
  for (const viewport of [{ name: "desktop", width: 1440, height: 1000 }, { name: "mobile", width: 390, height: 844 }]) {
    const page = await browser.newPage({ viewport });
    const errors = [];
    let online = false;
    let job = null;
    let starts = 0;
    let stops = 0;
    const record = () => ({
      id: runId, positionId: position.id, queueTag: null, model: "gpt-6-astra", harness: harnesses[2].id,
      config: { harness_name: "chess_harness", provider: "codex_mcp", teacher_reasoning_effort: "max" },
      status: job?.status === "cancelled" ? "failed" : job?.status === "completed" ? "completed" : "running",
      finalMoveUci: job?.result?.move.uci ?? null, cpLoss: null, classification: null, expectedPointsLoss: null,
      betterMoves: null, evaluation: null, failureStage: null, error: job?.error ?? null,
      createdAt: now, startedAt: now, finishedAt: null,
      passes: [{ runId, passNumber: 1, phase: "decide", toolCalls: [], workingNotes: "Vulnerabilities: Queen safety is unverified.", status: "completed", error: null, startedAt: now, finishedAt: now, hasModelExchange: true }],
    });
    page.on("pageerror", (error) => errors.push(error.message));
    await page.route((url) => url.pathname.startsWith("/api/"), async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      const path = url.pathname;
      const send = (json, status = 200) => route.fulfill({ json, status });
      if (path === "/api/codex-training/worker") return send({ configured: online, online, model: online ? "gpt-6-astra" : null, reasoning_effort: "max", active_run_id: job && !["completed", "cancelled"].includes(job.status) ? runId : null });
      if (path === "/api/codex-training/jobs" && request.method() === "POST") {
        starts++;
        assert.deepEqual(request.postDataJSON(), { position_id: position.id });
        job = { run_id: runId, position_id: position.id, status: "waiting", pass_number: 2, progress: "Writing pass 2", stopping: false, error: null, result: null };
        return send(job, 202);
      }
      if (path === `/api/codex-training/jobs/${runId}/stop` && request.method() === "POST") {
        stops++;
        job = { ...job, status: "cancelled", stopping: true, error: "Codex training run stopped." };
        return send(job, 202);
      }
      assert.equal(request.method(), "GET", `Unexpected mutation: ${path}`);
      if (path === `/api/codex-training/jobs/${runId}`) return send(job);
      if (path === "/api/models") return send({ server: url.searchParams.get("server"), models: [] });
      if (path === "/api/harnesses") return send(harnesses);
      if (path === "/api/folders") return send({ items: [], totalMatches: 0, unfiledCount: 0 });
      if (path === "/api/matches") return send({ items: [], total: 0 });
      if (path === "/api/positional-testing/positions") return send({ items: [position] });
      if (path === "/api/positional-testing/queues") return send({ items: [] });
      if (path === "/api/positional-testing/run-filters") return send({ datasets: ["v1"], models: ["gpt-6-astra"], harnesses, queues: [] });
      if (path === "/api/positional-testing/runs") return send({ items: job ? [record()] : [], total: job ? 1 : 0 });
      if (path.endsWith("/passes/1/exchange")) return send({ input: JSON.stringify({ input: [{ role: "user", content: "# Canonical position\n\nWhite to move." }] }), output: [explanation, response] });
      if (path === `/api/positional-testing/runs/${runId}`) return send(record());
      throw new Error(`Unexpected API request ${path}`);
    });
    await page.goto(baseUrl, { waitUntil: "networkidle" });
    await page.getByRole("button", { name: "Positional testing", exact: true }).click();
    const stage = page.getByRole("region", { name: "Position and test controls" });
    const codex = stage.getByRole("radio", { name: /Codex \(training\)/ });
    await stage.getByRole("radio", { name: /^chess_harness / }).check();
    assert.ok(await stage.getByRole("button", { name: "Run once", exact: true }).isDisabled(), "Normal harness still requires a loaded model");
    await codex.check();
    await stage.getByText(".\\scripts\\start-codex-worker.ps1", { exact: true }).waitFor();
    assert.ok(await stage.getByRole("button", { name: "Run once", exact: true }).isDisabled());
    online = true;
    await stage.getByText("gpt-6-astra · max reasoning", { exact: true }).waitFor();
    await stage.getByRole("button", { name: "Run once", exact: true }).click();
    await stage.getByText("Codex · pass 2", { exact: true }).waitFor();
    assert.ok(await codex.isDisabled());
    assert.equal(starts, 1);
    await page.reload({ waitUntil: "networkidle" });
    await page.getByRole("button", { name: "Positional testing", exact: true }).click();
    await stage.getByText("Codex · pass 2", { exact: true }).waitFor();
    assert.equal(starts, 1, "Reload reconnects instead of creating a second run");
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: resolve(directory, `codex-${viewport.name}.png`), fullPage: true, animations: "disabled" });
    await stage.locator(".position-inspector").screenshot({ path: resolve(directory, `codex-${viewport.name}-controls.png`), animations: "disabled" });
    await stage.getByRole("button", { name: "Stop Codex", exact: true }).click();
    await stage.getByText("Codex run stopped.", { exact: true }).waitFor();
    assert.equal(stops, 1);
    await stage.getByRole("button", { name: "Try again", exact: true }).click();
    await stage.getByText("Codex · pass 2", { exact: true }).waitFor();
    job = { ...job, status: "completed", result: { runId, positionId: position.id, positionName: position.name, harnessId: harnesses[2].id, harnessName: "chess_harness", harnessVersion: "v1", model: "gpt-6-astra", side: "white", ply: 38, move: { san: "Be5", uci: "f4e5", fromSquare: "f4", toSquare: "e5" }, justification: "Browser fixture only.", defenseReport: null, attackReport: null } };
    await stage.getByText("Move Be5 proposed", { exact: true }).waitFor();
    assert.equal(await stage.getByRole("button", { name: "Run again", exact: true }).isDisabled(), false);
    await page.getByRole("article", { name: "Pass 1", exact: true }).getByRole("button", { name: "Expand", exact: true }).click();
    const viewer = page.locator(".model-exchange-view");
    await viewer.getByText(explanation, { exact: true }).waitFor();
    assert.ok((await viewer.textContent()).includes("<agent_tool_calls>"));
    await viewer.getByRole("button", { name: "Back to previous view" }).click();
    assert.deepEqual(errors, []);
    await page.close();
  }
  console.log("Codex UI: offline recovery, independent model readiness, start, reload, stop, completion, and expanded explanation passed at desktop/mobile sizes.");
} finally { await browser.close(); }
