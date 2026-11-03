// All API traffic is mocked. This never starts or cancels a real run.
import assert from "node:assert/strict";
import { existsSync, mkdirSync } from "node:fs";
import { resolve } from "node:path";
import { chromium } from "playwright-core";

const executablePath = ["C:/Program Files/Google/Chrome/Application/chrome.exe", "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"].find(existsSync);
assert.ok(executablePath);
const directory = resolve("../.impeccable/review");
mkdirSync(directory, { recursive: true });
const uuid = (n) => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const harness = { id: "agent-player-2-langgraph-v1", name: "chess_harness", version: "v1", summary: "Browser fixture" };
const harnesses = ["Baseline", "legacy", "chess_harness", "chess_charness_alt"].map((name, i) => ({ ...harness, id: i ? `agent-player-${i}-langgraph-v1` : "baseline-direct-submit-langgraph-v1", name }));
const now = new Date().toISOString();
const positions = [1, 2, 3].map((n) => ({
  id: uuid(n), name: `Middlegame · move ${20 + n}`, datasetVersion: "v1", split: "train", phase: "middlegame", positionType: "quiet", sideToMove: "white", moveCount: 38,
  source: "lichess_game", sourceGameId: "fixture", sourceUrl: "https://lichess.org/0wtBizME", opening: "Alekhine Defense: Exchange Variation", themes: [], puzzleRating: null,
  position: { ply: 38, fen: "r1b1r1k1/pp3ppp/5q2/3p4/1P1P1B2/P2Q3P/5PP1/2R2RK1 w - - 1 20", san: "Qf6", player: "black", fromSquare: "d8", toSquare: "f6" },
}));
const browser = await chromium.launch({ executablePath, headless: true });
try {
  for (const viewport of [{ name: "desktop", width: 1440, height: 1000 }, { name: "mobile", width: 390, height: 844 }]) {
    for (const mode of ["queue", "single", "codex"]) {
      const page = await browser.newPage({ viewport });
      const errors = [];
      page.on("pageerror", (error) => errors.push(error.message));
      let activeId = mode === "queue" ? uuid(102) : mode === "codex" ? uuid(200) : null;
      let cancelled = false;
      let rejectCancel = true;
      let discardId;
      let cancelCount = 0;
      let terminalCancelStatus = null;
      let releaseSingle;
      const queue = {
        id: uuid(1000), name: "Cancellation preview", datasetVersion: "v1", split: "train", harnessId: harness.id, harnessName: "Codex (training)", harnessVersion: "v1",
        modelSelection: { modelId: "codex", modelName: "gpt-6-astra", reasoningEffort: "xhigh" }, status: "running", total: 3, completed: 1, failed: 0, pending: 1, running: 1, skipped: 0, createdAt: now, startedAt: now, finishedAt: null,
        items: positions.map((position, i) => ({ queueTag: uuid(1000), ordinal: i + 1, positionId: position.id, runId: uuid(101 + i), status: ["completed", "running", "queued"][i], phase: "middlegame", positionType: "quiet", finalMoveUci: null, classification: null, error: null, failureStage: null, startedAt: now, finishedAt: null })),
      };
      const job = () => ({ run_id: activeId ?? uuid(200), position_id: positions[0].id, queue_tag: null, status: cancelled ? "cancelled" : "waiting", pass_number: 5, progress: "Evaluating replies", error: null, result: null, stopping: false });
      await page.route((url) => url.pathname.startsWith("/api/"), async (route) => {
        const request = route.request();
        const url = new URL(request.url());
        const path = url.pathname;
        const send = (json, status = 200) => route.fulfill({ json, status });
        if (path.endsWith("/cancel") && request.method() === "POST") {
          if (terminalCancelStatus) {
            assert.equal(path, `/api/positional-testing/runs/${activeId}/cancel`);
            queue.items[1].status = "completed";
            queue.completed = 2;
            queue.running = 0;
            queue.status = "completed";
            activeId = null;
            return send({ detail: "This run is no longer active. Refresh to see its current status." }, terminalCancelStatus);
          }
          discardId ??= activeId;
          assert.equal(path, `/api/positional-testing/runs/${discardId}/cancel`, "Retry must target the original run, even if the queue advances");
          if (rejectCancel) {
            rejectCancel = false;
            if (mode === "queue") {
              queue.items[1].status = "failed";
              queue.items[1].error = "Database temporarily unavailable";
              queue.items[2].status = "running";
              queue.failed = 1;
              queue.pending = 0;
              activeId = queue.items[2].runId;
            }
            return send({ detail: "Temporary cancellation failure. Try again." }, 503);
          }
          cancelCount++;
          const oldId = discardId;
          cancelled = true;
          if (mode === "queue") {
            queue.items = queue.items.filter((item) => item.runId !== oldId);
            queue.items[1].status = "running";
            queue.total = 2;
            queue.failed = 0;
            queue.pending = 0;
            activeId = queue.items[1].runId;
          } else activeId = null;
          releaseSingle?.();
          return route.fulfill({ status: 204 });
        }
        if (path === "/api/positional-testing/runs" && request.method() === "POST") {
          assert.equal(mode, "single");
          activeId = request.postDataJSON().runId;
          assert.ok(activeId);
          await new Promise((resolve) => { releaseSingle = resolve; });
          return send({ detail: "Run cancelled and discarded." }, 409);
        }
        assert.equal(request.method(), "GET", `Unexpected mutation: ${path}`);
        if (path === "/api/models") return send({ server: "lmstudio", models: ["fixture-model"] });
        if (path === "/api/harnesses") return send(harnesses);
        if (path === "/api/folders") return send({ items: [], totalMatches: 0, unfiledCount: 0 });
        if (path === "/api/matches") return send({ items: [], total: 0 });
        if (path === "/api/codex-training/worker") return send({ configured: true, online: true, model: "gpt-6-astra", reasoning_effort: "xhigh", active_run_id: mode === "single" ? null : activeId, active_queue_id: mode === "queue" ? queue.id : null });
        if (path.startsWith("/api/codex-training/jobs/")) return send(job());
        if (path === "/api/positional-testing/positions") return send({ items: positions });
        if (path === "/api/positional-testing/queues") return send({ items: mode === "queue" ? [queue] : [] });
        if (path === `/api/positional-testing/queues/${queue.id}`) return send(queue);
        if (path === "/api/positional-testing/run-filters") return send({ datasets: ["v1"], models: [], harnesses: [harness], queues: [] });
        if (path === "/api/positional-testing/runs") return send({ items: [], total: 0 });
        throw new Error(`Unexpected request: ${path}`);
      });
      await page.goto(process.env.POSITION_UI_URL ?? "http://127.0.0.1:5187", { waitUntil: "networkidle" });
      await page.getByRole("button", { name: "Positional testing", exact: true }).click();
      if (mode === "single") {
        await page.getByRole("radio", { name: /chess_harness/ }).check();
        await page.getByRole("button", { name: "Run once", exact: true }).click();
      }
      const cancel = page.getByRole("button", { name: mode === "queue" ? "Cancel current run" : "Cancel run", exact: true });
      await cancel.waitFor();
      await cancel.scrollIntoViewIfNeeded();
      if (mode !== "codex") await page.screenshot({ path: resolve(directory, `cancel-${mode}-${viewport.name}.png`) });
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), "No horizontal page overflow");
      await cancel.click();
      await page.getByRole("alert").filter({ hasText: "Temporary cancellation failure. Try again." }).waitFor();
      assert.equal(cancelCount, 0);
      assert.equal(await page.getByText("The agent did not return a move.", { exact: true }).count(), 0);
      if (mode === "queue") {
        await page.getByText(`Position 3: ${positions[2].name}`, { exact: true }).waitFor();
        assert.ok(await cancel.isDisabled());
      } else {
        await page.getByText("Cancellation needs attention", { exact: true }).waitFor();
      }
      const retry = page.getByRole("button", { name: "Retry discard", exact: true });
      await retry.scrollIntoViewIfNeeded();
      await page.screenshot({ path: resolve(directory, `cancel-error-${mode}-${viewport.name}.png`) });
      await retry.click();
      await page.getByText("Run discarded. Its passes and results have been removed.", { exact: true }).waitFor();
      assert.equal(cancelCount, 1);
      if (mode === "queue") {
        await page.getByText("1 / 2 attempted", { exact: true }).waitFor();
        await page.getByText(`Position 3: ${positions[2].name}`, { exact: true }).waitFor();
        assert.equal(queue.completed, 1);
        terminalCancelStatus = viewport.name === "desktop" ? 409 : 404;
        await cancel.click();
        const terminalMessage = page.getByText("This run is no longer active. Refresh to see its current status.", { exact: true });
        await terminalMessage.waitFor();
        assert.ok(await page.locator(".position-queue__history select").isEnabled());
        assert.equal(await page.getByRole("button", { name: "Retry discard", exact: true }).count(), 0);
        await terminalMessage.scrollIntoViewIfNeeded();
        await page.screenshot({ path: resolve(directory, `cancel-terminal-queue-${viewport.name}.png`) });
      } else {
        assert.ok(await page.getByRole("button", { name: "Run once", exact: true }).isEnabled());
        assert.equal(await page.getByText("The agent did not return a move.", { exact: true }).count(), 0);
      }
      assert.deepEqual(errors, []);
      await page.close();
    }
  }
  console.log("Cancellation UI passed: queue, standard single, and Codex single at desktop/mobile widths; cancellation failure/retry and queue continuation verified.");
} finally {
  await browser.close();
}
