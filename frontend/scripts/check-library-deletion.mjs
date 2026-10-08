// Isolated browser fixtures: every API call is intercepted; no saved user data is deleted.
import assert from "node:assert/strict";
import { existsSync, mkdirSync } from "node:fs";
import { resolve } from "node:path";
import { chromium } from "playwright-core";

const executablePath = [process.env.CHROME_PATH, "C:/Program Files/Google/Chrome/Application/chrome.exe", "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", "/usr/bin/chromium"].find((path) => path && existsSync(path));
if (!executablePath) throw new Error("Set CHROME_PATH to a Chromium browser.");
const screenshots = resolve("../.impeccable/review");
mkdirSync(screenshots, { recursive: true });
const browser = await chromium.launch({ executablePath, headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1050 } });
page.setDefaultTimeout(10000);
const errors = [];
const deletions = [];
page.on("pageerror", (error) => errors.push(error.message));
const fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1";
const createdAt = "2026-10-06T12:00:00Z";
const queueId = "00000000-0000-0000-0000-000000000100";
const queueName = "Test queue · Baseline comparison";
const harness = { id: "baseline", name: "Baseline", version: "v1", summary: "Synthetic browser fixture" };
const makeRun = (index) => ({
  id: `00000000-0000-0000-0000-${String(index + 1).padStart(12, "0")}`,
  positionId: `position-${index}`, queueTag: [0, 1, 31].includes(index) ? queueId : null,
  queueName, model: "offline-test-model", harness: "baseline", config: { harness_name: "Baseline", queue_ordinal: index + 1 },
  status: "completed", finalMoveUci: "e2e4", cpLoss: 0, classification: "best", expectedPointsLoss: 0,
  betterMoves: [], evaluation: { status: "completed" }, failureStage: null, error: null,
  createdAt, startedAt: createdAt, finishedAt: createdAt, positionFen: fen,
  datasetVersion: "positions-v1", split: "test", phase: "opening", positionType: "quiet",
  analysisStatus: index === 31 ? "missing" : "completed", passes: [],
});
let runs = Array.from({ length: 32 }, (_, index) => makeRun(index));
let matches = [1, 2].map((index) => ({
  id: `match-fixture-${index}`, white: { harnessId: "baseline", name: "Baseline", version: "v1", color: "white" },
  black: { harnessId: "agent-3", name: "Agent Player 3", version: "v3", color: "black" },
  status: "stopped", result: "aborted", startedAt: createdAt, endedAt: createdAt,
  currentFen: fen, moveCount: 0, lastMove: null, currentPlayer: null, currentPhase: null,
  terminationReason: "Stopped", folder: null,
  positions: [{ ply: 0, fen, san: "Start", player: null, fromSquare: null, toSquare: null }], traces: [],
}));
let refuseDelete = false;
let holdDelete = null;

await page.route("**/api/**", async (route) => {
  const request = route.request();
  const url = new URL(request.url());
  const path = url.pathname;
  if (!path.startsWith("/api/")) return route.continue();
  const json = (value, status = 200) => route.fulfill({ status, json: value });
  if (request.method() === "DELETE") {
    deletions.push(path);
    if (holdDelete) await holdDelete;
    if (refuseDelete) return json({ detail: "This queue is still active. Stop it in Positional testing and wait for the current run to finish before deleting it." }, 409);
    const id = path.split("/").at(-1);
    if (path.includes("/queues/")) runs = runs.filter((run) => run.queueTag !== id);
    else if (path.includes("/runs/")) runs = runs.filter((run) => run.id !== id);
    else if (path.includes("/matches/")) matches = matches.filter((match) => match.id !== id);
    else throw new Error(`Unexpected delete: ${path}`);
    return route.fulfill({ status: 204 });
  }
  assert.equal(request.method(), "GET", `Unexpected mutation: ${request.method()} ${path}`);
  if (path === "/api/harnesses") return json([harness]);
  if (path === "/api/folders") return json({ items: [], totalMatches: matches.length, unfiledCount: matches.length });
  if (path === "/api/matches") return json({ items: matches, total: matches.length });
  if (path.startsWith("/api/matches/")) return json(matches.find((match) => match.id === path.split("/").at(-1)));
  if (path === "/api/positional-testing/positions" || path === "/api/positional-testing/queues") return json({ items: [] });
  if (path === "/api/positional-testing/run-filters") return json({
    datasets: ["positions-v1"], models: ["offline-test-model"], harnesses: [harness],
    queues: runs.some((run) => run.queueTag === queueId) ? [{ id: queueId, name: queueName, datasetVersion: "positions-v1", split: "test", harnessName: "Baseline", createdAt }] : [],
  });
  if (path === "/api/positional-testing/runs") {
    const filtered = runs.filter((run) => (!url.searchParams.get("queue_tag") || run.queueTag === url.searchParams.get("queue_tag")) && (!url.searchParams.get("analysis") || run.analysisStatus === url.searchParams.get("analysis")));
    const offset = Number(url.searchParams.get("offset") || 0);
    return json({ items: filtered.slice(offset, offset + 30), total: filtered.length });
  }
  if (path.startsWith("/api/positional-testing/runs/")) {
    const run = runs.find((run) => run.id === path.split("/").at(-1));
    return run ? json(run) : json({ detail: "Run not found." }, 404);
  }
  throw new Error(`Unexpected API request: ${path}`);
});

const dialog = page.getByRole("dialog");
const library = page.getByRole("region", { name: "Positional runs", exact: true });
const chooser = page.getByRole("group", { name: "Library type" });
const visibleRows = library.locator(".library-run-row");
const capture = async (name) => {
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, "No horizontal overflow");
  await page.screenshot({ path: resolve(screenshots, name), fullPage: false });
};

try {
  await page.goto(process.env.POSITION_UI_URL ?? "http://localhost:5173", { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "Match library", exact: true }).click();
  const matchDelete = page.getByRole("button", { name: "Delete match match-fixture-1", exact: true });
  await matchDelete.waitFor();
  await capture("delete-matches-desktop.png");
  await page.setViewportSize({ width: 390, height: 844 });
  await matchDelete.scrollIntoViewIfNeeded();
  await capture("delete-matches-mobile.png");
  await page.setViewportSize({ width: 1440, height: 1050 });
  await matchDelete.click();
  assert.equal(await dialog.getByRole("button", { name: "Delete entire queue" }).count(), 0);
  assert.equal(await dialog.getByRole("button", { name: "Cancel" }).evaluate((node) => document.activeElement === node), true);
  await page.keyboard.press("Escape");
  await page.waitForFunction(() => document.activeElement?.getAttribute("aria-label") === "Delete match match-fixture-1");
  assert.equal(await matchDelete.evaluate((node) => document.activeElement === node), true);
  assert.equal(deletions.length, 0);
  await matchDelete.click();
  await dialog.getByRole("button", { name: "Delete match", exact: true }).click();
  await matchDelete.waitFor({ state: "detached" });
  await page.getByText("1 found", { exact: true }).waitFor();
  await page.getByRole("button", { name: "Match desk", exact: true }).click();
  await page.getByRole("heading", { name: "Your first match starts here" }).waitFor();
  await page.getByRole("button", { name: "Match library", exact: true }).click();
  await page.getByRole("button", { name: "Delete match match-fixture-2", exact: true }).click();
  await dialog.getByRole("button", { name: "Delete match", exact: true }).click();
  await page.getByText("0 found", { exact: true }).waitFor();

  await chooser.getByRole("button", { name: /Positional testing/ }).click();
  await visibleRows.first().waitFor();
  await library.getByRole("region", { name: "Selected run", exact: true }).getByRole("grid").waitFor();
  await visibleRows.nth(1).click();
  const firstRunId = makeRun(0).id;
  const firstTrash = library.getByRole("button", { name: `Delete run ${firstRunId}`, exact: true });
  await visibleRows.first().scrollIntoViewIfNeeded();
  await capture("delete-positions-desktop.png");
  await page.setViewportSize({ width: 390, height: 844 });
  await firstTrash.scrollIntoViewIfNeeded();
  await capture("delete-positions-mobile.png");
  await page.setViewportSize({ width: 1440, height: 1050 });
  await firstTrash.click();
  assert.equal(await visibleRows.nth(1).getAttribute("aria-pressed"), "true", "Trash must not change the selected run");
  await dialog.getByText(queueName, { exact: true }).waitFor();
  await capture("delete-queue-desktop.png");
  await page.setViewportSize({ width: 390, height: 844 });
  await capture("delete-queue-mobile.png");
  await page.keyboard.press("Escape");
  await page.waitForFunction((id) => document.activeElement?.getAttribute("aria-label") === `Delete run ${id}`, firstRunId);
  assert.equal(await firstTrash.evaluate((node) => document.activeElement === node), true);
  await firstTrash.click();
  await dialog.getByRole("button", { name: "Delete this run" }).click();
  await firstTrash.waitFor({ state: "detached" });
  await library.getByText("31 runs recorded", { exact: true }).waitFor();
  assert.equal(runs.filter((run) => run.queueTag === queueId).length, 2);
  assert.equal(await visibleRows.first().getAttribute("aria-pressed"), "true");
  await page.setViewportSize({ width: 1440, height: 1050 });
  await library.getByRole("combobox", { name: "Queue run", exact: true }).selectOption(queueId);
  await library.getByRole("combobox", { name: "Engine analysis", exact: true }).selectOption("completed");
  await library.getByRole("button", { name: "Apply filters" }).click();
  await library.getByText("1 run matching filters", { exact: true }).waitFor();
  await library.getByRole("button", { name: `Delete run ${makeRun(1).id}`, exact: true }).click();
  refuseDelete = true;
  await dialog.getByRole("button", { name: "Delete entire queue" }).click();
  await dialog.getByRole("alert").waitFor();
  assert.equal(runs.length, 31, "Failed deletion preserves records");
  refuseDelete = false;
  let release;
  holdDelete = new Promise((resolve) => { release = resolve; });
  await dialog.getByRole("button", { name: "Delete entire queue" }).click();
  await dialog.getByRole("status").waitFor();
  assert.equal(await dialog.getByRole("button", { name: "Cancel" }).isDisabled(), true);
  await page.keyboard.press("Escape");
  assert.equal(await dialog.isVisible(), true, "Pending deletion keeps protected focus");
  release();
  holdDelete = null;
  await library.getByText("29 runs matching filters", { exact: true }).waitFor();
  assert.equal(runs.some((run) => run.queueTag === queueId), false, "Entire queue includes the filtered-out run");
  assert.equal(await library.getByRole("combobox", { name: "Queue run", exact: true }).inputValue(), "");
  assert.equal(await library.getByRole("combobox", { name: "Queue run", exact: true }).locator(`option[value="${queueId}"]`).count(), 0);

  // Last row on a later page moves back to the preceding page, then handles empty history.
  runs = Array.from({ length: 31 }, (_, index) => ({ ...makeRun(index + 50), queueTag: null }));
  await library.getByRole("button", { name: "Clear filters", exact: true }).first().click();
  await library.getByText("31 runs recorded", { exact: true }).waitFor();
  await library.getByRole("button", { name: "Next positional runs" }).click();
  await library.getByText("31–31 of 31", { exact: true }).waitFor();
  await library.getByRole("button", { name: `Delete run ${runs.at(-1).id}`, exact: true }).click();
  assert.equal(await dialog.getByRole("button", { name: "Delete entire queue" }).count(), 0);
  await dialog.getByRole("button", { name: "Delete this run" }).click();
  await library.getByText("1–30 of 30", { exact: true }).waitFor();
  runs = [runs[0]];
  await library.getByRole("button", { name: "Refresh runs", exact: true }).click();
  await library.getByText("1 run recorded", { exact: true }).waitFor();
  await library.getByRole("button", { name: `Delete run ${runs[0].id}`, exact: true }).click();
  await dialog.getByRole("button", { name: "Delete this run" }).click();
  await library.getByRole("heading", { name: "No positional runs yet" }).waitFor();
  assert.equal(await library.getByRole("region", { name: "Selected run", exact: true }).count(), 0);
  await page.reload({ waitUntil: "networkidle" });
  await page.getByRole("button", { name: "Match library", exact: true }).click();
  await page.getByText("0 found", { exact: true }).waitFor();
  await chooser.getByRole("button", { name: /Positional testing/ }).click();
  await library.getByRole("heading", { name: "No positional runs yet" }).waitFor();
  assert.deepEqual(errors, []);
  console.log("PASS: single-run and queue deletion, cancel/focus, retry/pending, counts, selection, filters, pagination, empty states, reload, desktop/mobile; all API calls mocked.");
} catch (error) {
  console.error("Browser errors:", errors);
  console.error((await page.locator("body").innerText()).slice(0, 4000));
  throw error;
} finally {
  await browser.close();
}
