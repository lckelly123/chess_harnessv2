// Synthetic queue/model responses; reads the real frozen library, never calls a model.
import assert from "node:assert/strict";
import { existsSync, mkdirSync } from "node:fs";
import { resolve } from "node:path";
import { chromium } from "playwright-core";

const executablePath = [process.env.CHROME_PATH, "C:/Program Files/Google/Chrome/Application/chrome.exe", "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", "/usr/bin/chromium"].find((path) => path && existsSync(path));
if (!executablePath) throw new Error("Set CHROME_PATH to a Chromium browser.");
const baseUrl = process.env.POSITION_UI_URL ?? "http://localhost:5173";
const screenshots = resolve("../.impeccable/review");
mkdirSync(screenshots, { recursive: true });
const browser = await chromium.launch({ executablePath, headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });
const errors = [];
page.on("pageerror", (error) => errors.push(error.message));
const uuid = (number) => `00000000-0000-4000-8000-${String(number).padStart(12, "0")}`;
let queue = null;
let posts = 0;
let unavailable = false;
let record;
try {
  const positions = (await (await page.request.get(`${baseUrl}/api/positional-testing/positions`)).json()).items;
  await page.route("**/api/positional-testing/queues**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (unavailable) return route.fulfill({ status: 503, json: { detail: "Queue database unavailable. Retry to reconnect." } });
    if (request.method() === "POST" && url.pathname.endsWith("/queues")) {
      posts += 1;
      assert.equal(posts, 1, "A duplicate start must not be sent");
      const input = request.postDataJSON();
      assert.equal(input.split, "test");
      assert.equal(input.harnessId, "agent-player-3-langgraph-v1");
      assert.ok(input.modelSelection.modelId);
      const selected = positions.filter((p) => p.split === input.split && p.datasetVersion === input.datasetVersion);
      assert.equal(selected.length, 200);
      const now = new Date().toISOString();
      queue = { id: uuid(1000), ...input, harnessName: "Agent Player 3", harnessVersion: "v1", status: "running", total: 200, completed: 1, failed: 1, pending: 197, running: 1, skipped: 0, createdAt: now, startedAt: now, finishedAt: null,
        items: selected.map((p, index) => ({ queueId: uuid(1000), ordinal: index + 1, positionId: p.id, runId: index < 3 ? uuid(index + 1) : null, status: index === 0 ? "completed" : index === 1 ? "failed" : index === 2 ? "running" : "queued", phase: p.phase, positionType: p.positionType, finalMoveUci: index === 0 ? "e2e4" : null, classification: index === 0 ? "good" : null, failureStage: index === 1 ? "execution" : null, error: index === 1 ? "Scripted provider failure: model response exceeded its time limit. The queue continued to the next position." : null, startedAt: index < 3 ? now : null, finishedAt: index < 2 ? now : null })) };
      record = { id: uuid(2), positionId: selected[1].id, model: "offline-browser-fixture", harness: input.harnessId, config: { harness_name: "Agent Player 3" }, status: "failed", finalMoveUci: null, cpLoss: null, classification: null, expectedPointsLoss: null, betterMoves: null, evaluation: null, error: queue.items[1].error, startedAt: now, finishedAt: now, passes: [{ runId: uuid(2), passNumber: 1, phase: "decide", toolCalls: [], workingNotes: "Synthetic browser fixture: model pass captured before the provider failure.", status: "failed", error: "Scripted provider failure", startedAt: now, finishedAt: now }] };
      return route.fulfill({ status: 202, json: queue });
    }
    if (request.method() === "POST" && url.pathname.endsWith("/stop")) {
      queue.status = "stopping";
      return route.fulfill({ json: queue });
    }
    assert.equal(request.method(), "GET");
    return route.fulfill({ json: url.pathname.endsWith("/queues") ? { items: queue ? [queue] : [] } : queue });
  });
  await page.route("**/api/positional-testing/runs**", async (route) => {
    assert.equal(route.request().method(), "GET", "Do not call a real model");
    const url = new URL(route.request().url());
    const found = record && (!url.searchParams.get("position_id") || url.searchParams.get("position_id") === record.positionId);
    return route.fulfill({ json: url.pathname.endsWith("/runs") ? { items: found ? [record] : [], total: found ? 1 : 0 } : record });
  });
  await page.goto(baseUrl, { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "Positional testing", exact: true }).click();
  const section = page.getByRole("region", { name: "Run a full set", exact: true });
  const start = section.getByRole("button", { name: "Run full queue · 200", exact: true });
  assert.ok(await start.isDisabled());
  await section.getByRole("combobox", { name: "Position set", exact: true }).selectOption("test");
  await section.getByRole("combobox", { name: "Queue harness", exact: true }).selectOption("agent-player-3-langgraph-v1");
  // The library's single-position search must not alter the full queue membership.
  await page.getByLabel("Search positions").fill(positions[0].id);
  await start.click();
  await section.getByText("2 / 200 attempted", { exact: true }).waitFor();
  assert.ok(await start.isDisabled());
  await section.getByRole("button", { name: "1 failed", exact: true }).click();
  await section.getByText(queue.items[1].error, { exact: false }).waitFor();
  assert.equal(await section.locator(".position-queue__item").count(), 1);
  await section.getByRole("button", { name: "View trace", exact: true }).focus();
  await page.keyboard.press("Enter");
  const history = page.getByRole("region", { name: "Run history", exact: true });
  await history.getByText(record.passes[0].workingNotes).waitFor();
  assert.ok(await history.evaluate((node) => node === document.activeElement), "Trace navigation moves keyboard focus to history");
  await page.keyboard.press("Tab");
  assert.ok(await history.getByRole("button", { name: "Refresh run history" }).evaluate((node) => node === document.activeElement));
  assert.equal(await history.getByLabel("Run ID", { exact: true }).inputValue(), record.id);
  assert.equal(await history.getByLabel("Position ID", { exact: true }).inputValue(), record.positionId);
  await section.getByLabel("Show failures only").uncheck();
  await section.getByRole("button", { name: "View position", exact: true }).first().focus();
  await page.keyboard.press("Enter");
  await page.waitForFunction(() => document.activeElement?.classList.contains("position-stage"));
  assert.equal(await page.getByRole("region", { name: "Position and test controls" }).evaluate((node) => getComputedStyle(node).outlineStyle), "solid");
  await page.reload({ waitUntil: "networkidle" });
  await page.getByRole("button", { name: "Positional testing", exact: true }).click();
  await section.getByText("2 / 200 attempted", { exact: true }).waitFor();
  assert.equal(posts, 1);
  await section.getByRole("button", { name: "1 failed", exact: true }).click();
  await page.waitForFunction(() => getComputedStyle(document.querySelector('.position-queue__items[open] > summary > svg')).transform === "matrix(0, 1, -1, 0, 0, 0)");
  await section.getByLabel("Show failures only").uncheck();
  assert.equal(await section.locator(".position-queue__item").count(), 200);
  assert.ok(await section.locator(".position-queue__list").evaluate((node) => node.scrollHeight > node.clientHeight));
  await section.scrollIntoViewIfNeeded();
  await section.screenshot({ path: resolve(screenshots, "queue-desktop.png"), animations: "disabled" });
  await page.setViewportSize({ width: 390, height: 844 });
  await section.getByRole("button", { name: "1 failed", exact: true }).click();
  await section.screenshot({ path: resolve(screenshots, "queue-mobile.png"), animations: "disabled" });
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), "No mobile page overflow");
  await page.setViewportSize({ width: 320, height: 740 });
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), "No 320px overflow");
  await section.getByRole("button", { name: "Stop after current", exact: true }).click();
  await section.getByRole("button", { name: "Stopping after current…", exact: true }).waitFor();
  queue.status = "stopped";
  queue.completed = 2;
  queue.running = 0;
  queue.skipped = 197;
  queue.pending = 0;
  queue.items[2].status = "completed";
  for (const item of queue.items.slice(3)) item.status = "skipped";
  await section.getByText("0 waiting · 197 skipped", { exact: true }).waitFor();
  unavailable = true;
  await section.getByRole("alert").waitFor({ timeout: 6000 });
  assert.ok(await start.isDisabled());
  unavailable = false;
  await section.getByRole("button", { name: "Refresh queue", exact: true }).click();
  await section.getByRole("alert").waitFor({ state: "hidden" });
  assert.deepEqual(errors, []);
  console.log("Queue browser checks passed: 200-position request, duplicate prevention, live progress, failure trace, reload, stop, retry, desktop/mobile/320px layouts. Synthetic responses only.");
} finally {
  await browser.close();
}
