// Read-only browser checks; failures and empty states are simulated in the browser.
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
page.on("request", (request) => {
  if (request.url().includes("/api/")) assert.equal(request.method(), "GET", "Library browsing must be read-only");
});

try {
  const saved = await (await page.request.get(`${baseUrl}/api/positional-testing/runs?limit=1`)).json();
  const options = await (await page.request.get(`${baseUrl}/api/positional-testing/run-filters`)).json();
  await page.goto(baseUrl, { waitUntil: "networkidle" });
  await page.addStyleTag({ content: "*, *::before, *::after { animation: none !important; transition: none !important; }" });
  await page.getByRole("button", { name: "Match library", exact: true }).click();
  const chooser = page.getByRole("group", { name: "Library type" });
  await chooser.getByRole("button", { name: /Agent vs agent/ }).waitFor();
  const matches = page.locator(".history-ledger");
  await matches.getByRole("combobox", { name: "Order", exact: true }).selectOption("oldest");
  let dates = await matches.locator("time").evaluateAll((nodes) => nodes.map((node) => Date.parse(node.dateTime)));
  assert.deepEqual(dates, [...dates].sort((a, b) => a - b));
  await matches.getByRole("combobox", { name: "Order", exact: true }).selectOption("newest");
  dates = await matches.locator("time").evaluateAll((nodes) => nodes.map((node) => Date.parse(node.dateTime)));
  assert.deepEqual(dates, [...dates].sort((a, b) => b - a));
  if (dates.length) {
    await matches.locator(".history-open").first().click();
    await page.getByRole("heading", { name: "Match desk", exact: true }).waitFor();
    await page.getByRole("button", { name: "Match library", exact: true }).click();
  }
  await page.screenshot({ path: resolve(screenshots, "library-matches-desktop.png"), fullPage: true });

  await chooser.getByRole("button", { name: /Positional testing/ }).click();
  const library = page.getByRole("region", { name: "Positional runs", exact: true });
  const rows = library.locator(".library-run-row");
  const detail = library.getByRole("region", { name: "Selected run", exact: true });
  await rows.first().waitFor();
  await detail.getByRole("grid", { name: /^Saved position before/ }).waitFor();
  assert.equal(await rows.count(), Math.min(30, saved.total));
  if (saved.total > 30) {
    const firstId = await rows.first().locator("code").textContent();
    await library.getByRole("button", { name: "Next positional runs" }).click();
    await library.locator(".position-pagination").getByText(new RegExp(`31–.* of ${saved.total}`)).waitFor();
    assert.notEqual(await rows.first().locator("code").textContent(), firstId);
  }
  if (options.queues.length) {
    const queue = options.queues[0];
    const expected = await (await page.request.get(`${baseUrl}/api/positional-testing/runs?queue_tag=${queue.id}&split=${queue.split}&analysis=completed`)).json();
    await library.getByRole("combobox", { name: "Queue run", exact: true }).selectOption(queue.id);
    await library.getByRole("combobox", { name: "Position set", exact: true }).selectOption(queue.split);
    await library.getByRole("combobox", { name: "Engine analysis", exact: true }).selectOption("completed");
    await library.getByRole("button", { name: "Apply filters" }).click();
    await library.getByText(`${expected.total} ${expected.total === 1 ? "run" : "runs"} matching filters`, { exact: true }).waitFor();
    if (expected.total) {
      await detail.getByRole("grid").waitFor();
      assert.equal(await rows.first().locator("code").textContent(), expected.items[0].id);
      await library.getByRole("button", { name: "View queue runs" }).click();
      await rows.first().waitFor();
      assert.equal(await library.getByRole("combobox", { name: "Engine analysis", exact: true }).inputValue(), "");
    }
  }

  await library.getByLabel("Search positional runs").fill("no-such-run-library-check");
  await library.getByRole("button", { name: "Apply filters" }).click();
  await library.getByRole("heading", { name: "No runs match these filters" }).waitFor();
  assert.equal(await detail.count(), 0, "Empty results must clear the previous inspector");
  await library.getByRole("button", { name: "Clear filters", exact: true }).first().click();
  await rows.first().waitFor();
  await library.getByRole("combobox", { name: "Order", exact: true }).selectOption("oldest");
  const oldest = await (await page.request.get(`${baseUrl}/api/positional-testing/runs?sort=oldest&limit=1`)).json();
  await page.waitForFunction((expected) => document.querySelector(".library-run-row code")?.textContent === expected, oldest.items[0].id);

  let unavailable = true;
  await page.route("**/api/positional-testing/runs?**", (route) => unavailable ? route.fulfill({ status: 503, json: { detail: "Simulated database unavailable" } }) : route.continue());
  await library.getByRole("button", { name: "Refresh runs", exact: true }).click();
  await library.getByRole("heading", { name: "Run history unavailable" }).waitFor();
  unavailable = false;
  await library.getByRole("button", { name: "Retry history" }).click();
  await rows.first().waitFor();
  await page.unroute("**/api/positional-testing/runs?**");

  await library.getByRole("button", { name: "Clear filters", exact: true }).first().click();
  await rows.first().waitFor();
  await library.getByRole("combobox", { name: "Engine analysis", exact: true }).selectOption("completed");
  await library.getByRole("button", { name: "Apply filters" }).click();
  await rows.first().waitFor();
  await detail.getByRole("grid").waitFor();
  await detail.getByRole("button", { name: "Flip board", exact: true }).click();
  await detail.getByText(/Black perspective/).waitFor();
  await detail.getByRole("button", { name: "Flip board", exact: true }).click();
  if (await rows.count() > 1) {
    const secondId = await rows.nth(1).locator("code").textContent();
    await rows.nth(1).click();
    await detail.getByRole("grid").waitFor();
    await detail.locator(".run-metadata summary").click();
    await detail.getByText(secondId, { exact: true }).waitFor();
    await detail.locator(".run-metadata summary").click();
  }
  await chooser.getByRole("button", { name: /Agent vs agent/ }).click();
  await chooser.getByRole("button", { name: /Positional testing/ }).click();
  assert.equal(await library.getByRole("combobox", { name: "Engine analysis", exact: true }).inputValue(), "completed", "Source switching preserves filters");
  await detail.getByRole("grid").waitFor();
  await page.evaluate(() => window.scrollTo(0, 0));
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
  await page.screenshot({ path: resolve(screenshots, "library-positions-desktop.png"), fullPage: true });

  await page.setViewportSize({ width: 390, height: 844 });
  await page.evaluate(() => window.scrollTo(0, 0));
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, "No mobile horizontal overflow");
  await page.screenshot({ path: resolve(screenshots, "library-positions-mobile.png"), fullPage: true });
  await detail.evaluate((node) => window.scrollTo({ top: node.getBoundingClientRect().top + window.scrollY, behavior: "instant" }));
  await page.screenshot({ path: resolve(screenshots, "library-inspector-mobile.png") });
  await chooser.getByRole("button", { name: /Agent vs agent/ }).click();
  await page.evaluate(() => window.scrollTo(0, 0));
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
  await page.screenshot({ path: resolve(screenshots, "library-matches-mobile.png"), fullPage: true });
  assert.deepEqual(errors, []);
  console.log(`Match Library browser checks passed: ${saved.total} saved runs; sorting, combined filters, paging, selection, replay, retry, source switching, and desktop/mobile layouts.`);
} finally {
  await browser.close();
}
