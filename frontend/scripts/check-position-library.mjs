import assert from "node:assert/strict";
import { existsSync, mkdirSync } from "node:fs";
import { resolve } from "node:path";
import { chromium } from "playwright-core";

const executablePath = [process.env.CHROME_PATH, "C:/Program Files/Google/Chrome/Application/chrome.exe", "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", "/usr/bin/chromium"].find((path) => path && existsSync(path));
if (!executablePath) throw new Error("Set CHROME_PATH to a Chromium browser.");
const baseUrl = process.env.POSITION_UI_URL ?? "http://localhost:5173";
const screenshots = resolve("..", ".impeccable", "review");
mkdirSync(screenshots, { recursive: true });
const browser = await chromium.launch({ executablePath, headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const errors = [];
page.on("pageerror", (error) => errors.push(error.message));
try {
  await page.goto(baseUrl, { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "Positional testing", exact: true }).click();
  const workspace = page.getByRole("region", { name: "Positional testing workspace" });
  const count = workspace.locator(".position-index__header p");
  const records = (await (await page.request.get(`${baseUrl}/api/positional-testing/positions`)).json()).items;
  assert.equal(records.length, 400);
  await count.filter({ hasText: "400 of 400 positions" }).waitFor();
  assert.equal(await workspace.locator(".position-row").count(), 12);
  assert.equal(await workspace.getByText("Queen Blunder", { exact: false }).count(), 0);

  await workspace.getByLabel("Set", { exact: true }).selectOption("train");
  await count.filter({ hasText: "200 of 400 positions" }).waitFor();
  await workspace.getByLabel("Phase", { exact: true }).selectOption("middlegame");
  await count.filter({ hasText: "120 of 400 positions" }).waitFor();
  await workspace.getByLabel("Position type", { exact: true }).selectOption("quiet");
  await count.filter({ hasText: "96 of 400 positions" }).waitFor();
  await workspace.getByLabel("Side to move", { exact: true }).selectOption("white");
  await count.filter({ hasText: "48 of 400 positions" }).waitFor();
  const firstId = await workspace.locator(".position-record dd").first().textContent();
  const selected = records.find((record) => record.id === firstId);
  assert.ok(selected);
  assert.equal(await workspace.locator(".position-record dd").nth(1).textContent(), selected.position.fen);
  assert.equal(await workspace.getByRole("gridcell").count(), 64);
  await workspace.getByRole("button", { name: "Next positions", exact: true }).click();
  assert.notEqual(await workspace.locator(".position-record dd").first().textContent(), firstId);
  assert.match(await workspace.locator(".position-pagination").textContent(), /13–24 of 48/);
  await workspace.getByRole("button", { name: "Previous positions", exact: true }).click();

  await workspace.getByLabel("Search positions").fill("no-such-position-check");
  await workspace.getByText("No positions match these filters.").waitFor();
  assert.equal(await workspace.getByRole("button", { name: "Run once", exact: true }).count(), 0);
  const refreshed = page.waitForResponse((response) => response.url().endsWith("/api/positional-testing/positions"));
  await workspace.getByRole("button", { name: "Refresh position library", exact: true }).click();
  await refreshed;
  await workspace.getByText("No positions match these filters.").waitFor();
  assert.equal(await workspace.getByRole("grid").count(), 0, "Refreshing an empty filter must not select an unrelated board");
  assert.equal(await workspace.getByRole("button", { name: "Run once", exact: true }).count(), 0);
  await workspace.getByLabel("Search positions").fill("");
  await workspace.locator(".position-record dd").first().waitFor({ state: "attached" });
  const removedId = await workspace.locator(".position-record dd").first().textContent();
  await page.route("**/api/positional-testing/positions", (route) => route.fulfill({ contentType: "application/json", body: JSON.stringify({ items: records.filter((record) => record.id !== removedId) }) }));
  await workspace.getByRole("button", { name: "Refresh position library", exact: true }).click();
  await count.filter({ hasText: "47 of 399 positions" }).waitFor();
  const replacementId = await workspace.locator(".position-record dd").first().textContent();
  const replacementRecord = records.find((record) => record.id === replacementId);
  assert.notEqual(replacementId, removedId);
  assert.ok(replacementRecord?.split === "train" && replacementRecord.phase === "middlegame" && replacementRecord.positionType === "quiet" && replacementRecord.sideToMove === "white");
  await page.unroute("**/api/positional-testing/positions");
  await workspace.getByRole("button", { name: "Refresh position library", exact: true }).click();
  await count.filter({ hasText: "48 of 400 positions" }).waitFor();

  await workspace.getByRole("button", { name: "Clear filters", exact: true }).click();
  await workspace.locator(".position-filters__more summary").click();
  await workspace.getByLabel("Dataset", { exact: true }).selectOption("v1");
  await workspace.getByLabel("Source", { exact: true }).selectOption("lichess_puzzle");
  await count.filter({ hasText: "80 of 400 positions" }).waitFor();
  const theme = records.find((record) => record.themes.includes("pin")) ? "pin" : records.find((record) => record.themes.length).themes[0];
  await workspace.getByLabel("Puzzle theme", { exact: true }).selectOption(theme);
  const expected = records.filter((record) => record.themes.includes(theme)).length;
  await count.filter({ hasText: `${expected} of 400 positions` }).waitFor();
  assert.ok(await workspace.locator('[aria-label="Puzzle themes"] .position-tag').count() > 0);
  await workspace.getByLabel("Puzzle theme", { exact: true }).selectOption("");
  await workspace.getByLabel("Puzzle rating", { exact: true }).selectOption("1800plus");
  await count.filter({ hasText: `${records.filter((record) => record.puzzleRating >= 1800).length} of 400 positions` }).waitFor();
  await workspace.getByRole("button", { name: "Clear filters", exact: true }).click();
  await workspace.locator(".position-filters__more summary").click();

  // Exercise pending/error/retry state without calling any model.
  let pendingRoute;
  await page.route("**/api/positional-testing/runs", (route) => { pendingRoute = route; });
  await workspace.getByRole("radio", { name: /^Baseline/ }).check();
  await workspace.getByRole("button", { name: "Run once", exact: true }).click();
  await workspace.getByRole("button", { name: "Running one turn…", exact: true }).waitFor();
  assert.ok(await workspace.getByLabel("Set", { exact: true }).isDisabled());
  assert.ok(await workspace.locator(".position-row").first().isDisabled());
  await page.waitForRequest((request) => request.url().endsWith("/api/positional-testing/runs"), { timeout: 1000 }).catch(() => {});
  assert.ok(pendingRoute);
  const body = pendingRoute.request().postDataJSON();
  assert.equal(body.positionId, await workspace.locator(".position-record dd").first().textContent());
  assert.deepEqual(Object.keys(body).sort(), ["harnessId", "modelSelection", "positionId"]);
  await pendingRoute.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "Scripted check: model unavailable." }) });
  await workspace.getByText("Scripted check: model unavailable.").waitFor();
  assert.ok(await workspace.getByRole("button", { name: "Try again", exact: true }).isEnabled());
  await workspace.locator(".position-row").first().click();

  await workspace.getByLabel("Set", { exact: true }).selectOption("train");
  await workspace.getByLabel("Phase", { exact: true }).selectOption("middlegame");
  await workspace.getByLabel("Position type", { exact: true }).selectOption("quiet");
  await workspace.getByLabel("Side to move", { exact: true }).selectOption("white");
  await workspace.getByRole("radio", { name: /^Agent Player 3/ }).check();

  for (const viewport of [{ name: "desktop", width: 1440, height: 1000 }, { name: "mobile", width: 390, height: 844 }]) {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    await page.evaluate(() => document.fonts.ready);
    await page.evaluate(() => window.scrollTo(0, 0));
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), `${viewport.name}: horizontal overflow`);
    await page.screenshot({ path: resolve(screenshots, `position-library-${viewport.name}.png`), fullPage: true, animations: "disabled" });
  }
  assert.deepEqual(errors, []);
  console.log("Position library verified: 400 DB records, combined filters, themes, ratings, pagination, exact FEN, run payload/locking/retry, desktop/mobile without horizontal overflow. No model was called.");
} finally {
  await browser.close();
}
