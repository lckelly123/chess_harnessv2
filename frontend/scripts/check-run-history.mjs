// Uses an actual PostgreSQL/API roundtrip fixture; no live model calls or live DB mutations.
import assert from "node:assert/strict";
import { existsSync, mkdirSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { chromium } from "playwright-core";

const fixture = JSON.parse(readFileSync(resolve("../backend/.test-data/run-history-fixture.json"), "utf8"));
const executablePath = [process.env.CHROME_PATH, "C:/Program Files/Google/Chrome/Application/chrome.exe", "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", "/usr/bin/chromium"].find((path) => path && existsSync(path));
if (!executablePath) throw new Error("Set CHROME_PATH to a Chromium browser.");
const baseUrl = process.env.POSITION_UI_URL ?? "http://localhost:5173";
const screenshots = resolve("../.impeccable/review");
mkdirSync(screenshots, { recursive: true });
const browser = await chromium.launch({ executablePath, headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const errors = [];
page.on("pageerror", (error) => errors.push(error.message));
const id = (number) => `00000000-0000-4000-8000-${String(number).padStart(12, "0")}`;
let records = [];
let unavailable = false;
try {
  const positions = (await (await page.request.get(`${baseUrl}/api/positional-testing/positions`)).json()).items;
  const otherPosition = positions.find((p) => p.id !== fixture.positionId).id;
  const failed = { ...structuredClone(fixture), id: id(2), status: "failed", finalMoveUci: null, error: "Scripted provider failure", passes: [{ ...structuredClone(fixture.passes[0]), runId: id(2), status: "failed", error: "Scripted provider failure", toolCalls: [] }] };
  records = [fixture, failed, { ...structuredClone(fixture), id: id(3), positionId: otherPosition }];
  await page.route("**/api/positional-testing/runs**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    assert.equal(request.method(), "GET", "This check must not call a model");
    if (unavailable) return route.fulfill({ status: 503, json: { detail: "Run history is unavailable. Check the positions database and retry." } });
    if (url.pathname.endsWith("/runs")) {
      const selected = records.filter((r) => (!url.searchParams.get("position_id") || r.positionId === url.searchParams.get("position_id")) && (!url.searchParams.get("run_id") || r.id === url.searchParams.get("run_id")));
      const offset = Number(url.searchParams.get("offset") ?? 0);
      return route.fulfill({ json: { items: selected.slice(offset, offset + 30).map(({ passes, ...run }) => { void passes; return run; }), total: selected.length } });
    }
    const run = records.find((r) => r.id === url.pathname.split("/").pop());
    return route.fulfill({ status: run ? 200 : 404, json: run ?? { detail: "Run not found." } });
  });
  await page.goto(baseUrl, { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "Positional testing", exact: true }).click();
  await page.getByLabel("Search positions").fill(fixture.positionId);
  const history = page.getByRole("region", { name: "Run history", exact: true });
  await history.getByLabel("Position ID", { exact: true }).filter({ visible: true }).waitFor();
  await page.waitForFunction((expected) => document.querySelector('.run-history input')?.value === expected, fixture.positionId);
  await history.locator(".run-row").first().waitFor();
  assert.equal(await history.getByRole("button", { name: "Filter runs", exact: true }).evaluate((node) => getComputedStyle(node).borderRadius), "8px", "The server must serve the current styled controls");
  assert.equal(await history.locator(".run-tool summary svg").count(), 5, "The current disclosure icons must be loaded");
  assert.equal(await history.locator(".run-row").count(), 2);
  const detail = history.getByRole("region", { name: "Selected run", exact: true });
  await detail.getByText("Not evaluated", { exact: true }).waitFor();
  assert.equal(await detail.locator(".run-outcome__move").textContent(), fixture.finalMoveUci);
  assert.equal(await detail.getByRole("article").count(), 3);
  assert.equal(await detail.locator(".run-tool").count(), 5);
  await detail.getByRole("article", { name: "Pass 1", exact: true }).locator("summary").click();
  await detail.getByText("Arguments", { exact: true }).first().waitFor();
  await detail.getByText("Board context", { exact: true }).first().waitFor();
  assert.ok((await detail.getByRole("article", { name: "Pass 1", exact: true }).innerText()).includes("canonical_fen"));
  assert.ok(await detail.locator(".run-passes").evaluate((node) => node.scrollHeight > node.clientHeight));

  await history.getByLabel("Run ID", { exact: true }).fill(failed.id);
  await history.getByRole("button", { name: "Filter runs", exact: true }).click();
  await detail.getByText("No move submitted", { exact: true }).waitFor();
  assert.equal(await history.locator(".run-row").count(), 1);
  await history.getByLabel("Position ID", { exact: true }).fill(otherPosition);
  await history.getByRole("button", { name: "Filter runs", exact: true }).click();
  await history.getByText("No runs found", { exact: true }).waitFor();
  assert.equal(await history.getByRole("region", { name: "Selected run", exact: true }).count(), 0);
  await history.getByRole("button", { name: "All runs", exact: true }).click();
  await history.locator(".run-row").nth(2).waitFor();

  unavailable = true;
  await history.getByRole("button", { name: "Refresh run history", exact: true }).click();
  await history.getByRole("alert").waitFor();
  unavailable = false;
  await history.getByRole("button", { name: "Retry history", exact: true }).click();
  await history.locator(".run-row").nth(2).waitFor();

  const live = { ...structuredClone(fixture), id: id(4), status: "running", finalMoveUci: null, finishedAt: null, passes: [{ ...structuredClone(fixture.passes[0]), runId: id(4), status: "running", finishedAt: null }] };
  records.unshift(live);
  await history.getByLabel("Run ID", { exact: true }).fill(live.id);
  await history.getByRole("button", { name: "Filter runs", exact: true }).click();
  await detail.getByText("Awaiting move", { exact: true }).waitFor();
  records[0] = { ...structuredClone(fixture), id: live.id };
  await detail.getByText(fixture.finalMoveUci, { exact: true }).waitFor({ timeout: 7000 });
  assert.equal(await detail.getByRole("article").count(), 3);

  records = [fixture, ...Array.from({ length: 31 }, (_, i) => ({ ...structuredClone(fixture), id: id(i + 10) }))];
  await history.getByRole("button", { name: "All runs", exact: true }).click();
  await history.getByRole("button", { name: "Next runs", exact: true }).click();
  await history.locator(".position-pagination").getByText("31–32 of 32", { exact: true }).waitFor();
  assert.equal(await history.locator(".run-row").count(), 2);
  await history.getByRole("button", { name: "Previous runs", exact: true }).click();

  records = [fixture, failed];
  await history.getByLabel("Position ID", { exact: true }).fill(fixture.positionId);
  await history.getByRole("button", { name: "Filter runs", exact: true }).click();
  await detail.getByText("Not evaluated", { exact: true }).waitFor();
  await detail.getByRole("article", { name: "Pass 1", exact: true }).locator("summary").click();
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: resolve(screenshots, "run-history-desktop-full.png"), fullPage: true, animations: "disabled" });
  await history.screenshot({ path: resolve(screenshots, "run-history-desktop.png"), animations: "disabled" });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: resolve(screenshots, "run-history-mobile-full.png"), fullPage: true, animations: "disabled" });
  await history.screenshot({ path: resolve(screenshots, "run-history-mobile.png"), animations: "disabled" });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
  assert.deepEqual(errors, []);
  console.log(JSON.stringify({ checks: "ID filters, selection, notes/tools/results, failures, empty/error/retry, live polling, pagination, desktop/mobile", liveModelCalls: 0, productionDatabaseWrites: 0, screenshots }));
} finally {
  await browser.close();
}
