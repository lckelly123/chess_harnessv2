// All API traffic is mocked: this never starts a teacher or modifies saved runs.
import assert from "node:assert/strict";
import { existsSync, mkdirSync } from "node:fs";
import { resolve } from "node:path";
import { chromium } from "playwright-core";

const executablePath = [process.env.CHROME_PATH, "C:/Program Files/Google/Chrome/Application/chrome.exe", "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"].find((path) => path && existsSync(path));
assert.ok(executablePath, "A Chromium browser is required.");
const screenshots = resolve("../.impeccable/review");
mkdirSync(screenshots, { recursive: true });
const uuid = (number) => `00000000-0000-4000-8000-${String(number).padStart(12, "0")}`;
const harnesses = [{ id: "agent-player-2-langgraph-v1", name: "chess_harness", version: "v1", summary: "Browser fixture." }];
const positions = Array.from({ length: 3 }, (_, index) => ({
  id: uuid(index + 1), name: `Middlegame · move ${20 + index}`, datasetVersion: "v1", split: "train", phase: "middlegame", positionType: "quiet", sideToMove: "white", moveCount: 38,
  source: "lichess_game", sourceGameId: "0wtBizME", sourceUrl: "https://lichess.org/0wtBizME", opening: "Alekhine Defense: Exchange Variation", themes: [], puzzleRating: null,
  position: { ply: 38, fen: "r1b1r1k1/pp3ppp/5q2/3p4/1P1P1B2/P2Q3P/5PP1/2R2RK1 w - - 1 20", san: "Qf6", player: "black", fromSquare: "d8", toSquare: "f6" },
}));
const browser = await chromium.launch({ executablePath, headless: true });
try {
  for (const viewport of [{ name: "desktop", width: 1440, height: 1000 }, { name: "mobile", width: 390, height: 844 }]) {
    const page = await browser.newPage({ viewport });
    const errors = [];
    let online = false;
    let queue = null;
    let starts = 0;
    let jobReads = 0;
    let originalQueue = null;
    let pastQueue = null;
    let retries = 0;
    let rejectRetry = true;
    page.on("pageerror", (error) => errors.push(error.message));
    await page.route((url) => url.pathname.startsWith("/api/"), async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      const path = url.pathname;
      const send = (json, status = 200) => route.fulfill({ json, status });
      if (path === "/api/codex-training/worker") return send({ configured: true, online, model: "gpt-6-astra", reasoning_effort: "max", active_run_id: queue?.running ? queue.items[0].runId : null, active_queue_id: queue?.running ? queue.id : null });
      if (path.startsWith("/api/codex-training/jobs/")) { jobReads++; return send({ detail: "Queue jobs must not attach to single-run controls." }, 404); }
      if (path === "/api/positional-testing/queues" && request.method() === "POST") {
        starts++;
        assert.deepEqual(request.postDataJSON(), { name: "Codex · candidate checks", split: "train", datasetVersion: "v1", harnessId: "codex-training" });
        const now = new Date().toISOString();
        queue = { id: uuid(1000), name: "Codex · candidate checks", split: "train", datasetVersion: "v1", harnessId: harnesses[0].id, harnessName: "Codex (training)", harnessVersion: "v1", modelSelection: { modelId: "codex", modelName: "gpt-6-astra", reasoningEffort: "max" }, status: "running", total: 3, completed: 0, failed: 0, pending: 2, running: 1, skipped: 0, createdAt: now, startedAt: now, finishedAt: null,
          items: positions.map((position, index) => ({ queueTag: uuid(1000), ordinal: index + 1, positionId: position.id, runId: uuid(100 + index), status: index ? "queued" : "running", phase: position.phase, positionType: position.positionType, finalMoveUci: null, classification: null, error: null, failureStage: null, startedAt: index ? null : now, finishedAt: null })) };
        return send(queue, 202);
      }
      if (path.endsWith("/retry-failed") && request.method() === "POST") {
        assert.equal(path, `/api/positional-testing/queues/${uuid(900)}/retry-failed`, "Retry must target the explicitly chosen past queue, not the displayed/latest queue");
        assert.equal(request.postData(), null, "Retry uses the source settings, without sidebar overrides");
        if (rejectRetry) { rejectRetry = false; return send({ detail: "Fixture unavailable. Try again." }, 503); }
        retries++;
        originalQueue = structuredClone(queue);
        queue = { ...pastQueue, status: "running", pending: 2, failed: 0, skipped: 0, finishedAt: null,
          items: pastQueue.items.map((item, index) => ["failed", "skipped"].includes(item.status) ? { ...item, runId: uuid(3000 + index), status: "queued", error: null, failureStage: null, startedAt: null, finishedAt: null } : item) };
        pastQueue = queue;
        return send(queue, 202);
      }
      if (path.endsWith("/stop") && request.method() === "POST") {
        queue = { ...queue, status: "stopping", pending: 0, skipped: 2, items: queue.items.map((item) => item.status === "queued" ? { ...item, status: "skipped" } : item) };
        return send(queue);
      }
      assert.equal(request.method(), "GET", `Unexpected mutation: ${path}`);
      if (path === "/api/models") return send({ server: url.searchParams.get("server"), models: [] });
      if (path === "/api/harnesses") return send(harnesses);
      if (path === "/api/folders") return send({ items: [], totalMatches: 0, unfiledCount: 0 });
      if (path === "/api/matches") return send({ items: [], total: 0 });
      if (path === "/api/positional-testing/positions") return send({ items: positions });
      if (path === "/api/positional-testing/queues") return send({ items: queue ? [...new Map([queue, originalQueue, pastQueue].filter(Boolean).map((item) => [item.id, item])).values()] : [] });
      if (path === `/api/positional-testing/queues/${uuid(900)}`) return send(pastQueue);
      if (path === `/api/positional-testing/queues/${uuid(1000)}`) return send(originalQueue ?? queue);
      if (path === `/api/positional-testing/queues/${uuid(2000)}`) return send(queue);
      if (path === "/api/positional-testing/run-filters") return send({ datasets: ["v1"], models: [], harnesses, queues: [] });
      if (path === "/api/positional-testing/runs") return send({ items: [], total: 0 });
      throw new Error(`Unexpected API request ${path}`);
    });
    await page.goto(process.env.POSITION_UI_URL ?? "http://127.0.0.1:5173", { waitUntil: "networkidle" });
    await page.getByRole("button", { name: "Positional testing", exact: true }).click();
    const section = page.getByRole("region", { name: "Run a full set", exact: true });
    const harness = section.getByRole("combobox", { name: "Queue harness", exact: true });
    const start = section.getByRole("button", { name: "Run full queue · 3", exact: true });
    await harness.selectOption(harnesses[0].id);
    assert.ok(await start.isDisabled(), "Standard harness requires a loaded local model");
    await harness.selectOption("codex-training");
    await section.getByText(".\\scripts\\start-codex-worker.ps1", { exact: true }).waitFor();
    assert.ok(await start.isDisabled(), "Offline worker blocks Codex queue start");
    online = true;
    await section.getByText("Codex · gpt-6-astra · max reasoning", { exact: true }).waitFor();
    assert.ok(await start.isEnabled(), "Codex queue ignores the empty local model inventory");
    await section.getByLabel("Queue name (optional)").fill("Codex · candidate checks");
    await start.click();
    await section.getByText("0 / 3 attempted", { exact: true }).waitFor();
    assert.ok(await start.isDisabled());
    await page.reload({ waitUntil: "networkidle" });
    await page.getByRole("button", { name: "Positional testing", exact: true }).click();
    await section.getByText("0 / 3 attempted", { exact: true }).waitFor();
    await harness.selectOption("codex-training");
    await section.getByText("Positions and results", { exact: true }).click();
    assert.ok(await section.getByRole("button", { name: "View live trace", exact: true }).isEnabled(), "Queue worker does not block trace inspection as a single run");
    assert.equal(starts, 1, "Reload must not start another queue");
    assert.equal(jobReads, 0, "Queue worker does not attach to single-position UI");
    await section.screenshot({ path: resolve(screenshots, `codex-queue-${viewport.name}.png`), animations: "disabled" });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), "No viewport overflow");
    if (viewport.name === "mobile") {
      await page.setViewportSize({ width: 320, height: 740 });
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), "No 320px overflow");
    }
    // Waiting after a worker disconnect explains why unstarted positions remain queued.
    online = false;
    queue.running = 0;
    queue.failed = 1;
    queue.items[0].status = "failed";
    await section.getByText("Waiting for the Windows Codex worker.", { exact: false }).waitFor();
    await section.getByRole("button", { name: "Stop after current", exact: true }).click();
    await section.getByRole("button", { name: "Stopping after current…", exact: true }).waitFor();
    queue.status = "stopped";
    // A stopped queue with no failures must also appear when its positions were skipped.
    queue.failed = 0;
    queue.skipped = 3;
    queue.items.forEach((item) => { item.status = "skipped"; });
    pastQueue = { ...structuredClone(queue), id: uuid(900), name: "Original training run · before the latest retry", status: "stopped", completed: 1, failed: 1, skipped: 1,
      createdAt: "2026-10-14T12:00:00Z", modelSelection: { modelId: "codex", modelName: "gpt-6-astra", reasoningEffort: "xhigh" },
      items: queue.items.map((item, index) => ({ ...item, queueTag: uuid(900), runId: uuid(9000 + index), status: index === 1 ? "completed" : index === 0 ? "failed" : "skipped", classification: index === 1 ? "blunder" : null })) };
    const source = section.getByRole("combobox", { name: "Past queue", exact: true });
    const retry = section.getByRole("button", { name: /Retry unfinished positions/ });
    await source.locator(`option[value="${uuid(900)}"]`).waitFor({ state: "attached" });
    assert.equal(await source.inputValue(), "", "No past queue is selected implicitly");
    assert.ok(await retry.isDisabled(), "A past queue must be explicitly selected");
    await source.selectOption(uuid(1000));
    assert.match(await retry.textContent(), /3$/);
    assert.match(await source.locator("option:checked").textContent(), /0 failed · 3 skipped/);
    assert.ok(await retry.isDisabled(), "Codex retry requires its worker, independently of the sidebar");
    await source.selectOption(uuid(900));
    assert.match(await retry.textContent(), /2$/);
    assert.match(await source.locator("option:checked").textContent(), /1 failed · 1 skipped/);
    assert.equal(await section.getByLabel("Recent queues").inputValue(), uuid(1000), "Choosing a retry source does not change the displayed results");
    online = true;
    await page.waitForFunction(() => [...document.querySelectorAll("button")].some((button) => button.textContent.includes("Retry unfinished positions") && !button.disabled));
    await page.setViewportSize(viewport);
    await section.screenshot({ path: resolve(screenshots, `queue-retry-source-${viewport.name}.png`), animations: "disabled" });
    const originalSnapshot = structuredClone(queue);
    const pastSnapshot = structuredClone(pastQueue);
    await retry.click();
    await section.getByRole("alert").getByText("Fixture unavailable. Try again.").waitFor();
    assert.equal(queue.id, uuid(1000), "A failed retry preserves the selected source queue");
    assert.equal(await source.inputValue(), uuid(900), "A failed request preserves the explicit source selection");
    await retry.focus();
    await page.keyboard.press("Enter");
    await section.getByText("1 / 3 attempted", { exact: true }).waitFor();
    assert.equal(await section.locator(".position-queue__item").count(), 3);
    assert.equal(queue.id, pastSnapshot.id);
    assert.equal(queue.name, pastSnapshot.name);
    assert.equal(await section.getByLabel("Recent queues").locator("option").count(), 2, "Retry must not add another queue");
    assert.equal(retries, 1);
    assert.deepEqual(originalQueue, originalSnapshot);
    assert.deepEqual(queue.items[1], pastSnapshot.items[1], "Completed blunder is unchanged");
    assert.deepEqual(queue.modelSelection, pastSnapshot.modelSelection);
    assert.deepEqual(queue.items.filter((item) => item.status === "queued").map((item) => item.positionId), [positions[0].id, positions[2].id], "Failed and skipped positions restart; completed blunders are excluded");
    await section.screenshot({ path: resolve(screenshots, `queue-retry-source-result-${viewport.name}.png`), animations: "disabled" });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), "Retry lineage fits the viewport");
    await section.getByLabel("Recent queues").selectOption(originalQueue.id);
    await retry.waitFor();
    assert.equal(await source.inputValue(), "", "The running queue is no longer eligible for retry");
    assert.ok(await retry.isDisabled(), "An active retry prevents a duplicate queue");
    await page.reload({ waitUntil: "networkidle" });
    await page.getByRole("button", { name: "Positional testing", exact: true }).click();
    await section.getByText("1 / 3 attempted", { exact: true }).waitFor();
    assert.equal(retries, 1, "Reload must not start a second retry");
    assert.equal(await source.inputValue(), "");
    assert.ok(await retry.isDisabled());
    queue.status = "completed";
    queue.pending = 0;
    queue.completed = 3;
    queue.items.forEach((item) => { item.status = "completed"; });
    await section.getByText("3 / 3 attempted", { exact: true }).waitFor();
    assert.equal(await source.locator(`option[value="${queue.id}"]`).count(), 0, "Successful queues cannot be retry sources");
    await source.selectOption(uuid(1000));
    originalQueue = null;
    await source.locator(`option[value="${uuid(1000)}"]`).waitFor({ state: "detached" });
    assert.equal(await source.inputValue(), "", "A removed source clears the effective selection");
    assert.ok(await retry.isDisabled());
    assert.deepEqual(errors, []);
    await page.close();
  }
  console.log("Codex queue: readiness, start/reload/stop, explicit past-queue selection, skipped-only eligibility, failed/skipped retries in place, preserved successes and queue identity, source removal, duplicate prevention, desktop/mobile passed.");
} finally { await browser.close(); }
