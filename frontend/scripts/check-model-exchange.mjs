// Read-only integration check. New-capture responses are simulated in the browser;
// database/provider fidelity is covered by the backend exchange tests.
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
const capture = (options) => process.env.CAPTURE_SCREENSHOTS === "0" ? Promise.resolve() : page.screenshot(options);
const errors = [];
let exchangeRequests = 0;
let fail = false;
let empty = false;
let long = false;
let release;
page.on("pageerror", (error) => errors.push(error.message));
page.on("request", (request) => {
  if (request.url().includes("/api/")) assert.equal(request.method(), "GET", "Inspecting a pass must not run a model or mutate history");
});

try {
  const saved = await (await page.request.get(`${baseUrl}/api/positional-testing/runs?limit=1&status=completed`)).json();
  const run = await (await page.request.get(`${baseUrl}/api/positional-testing/runs/${saved.items[0].id}`)).json();
  assert.ok(run.passes.length, "Browser fixture needs a saved run with passes");
  const fixture = { ...run, status: "completed", passes: Array.from({ length: 4 }, (_, index) => ({
    ...run.passes[0], runId: run.id, passNumber: index + 1, hasModelExchange: index < 3,
  })) };
  const exchange = {
    input: JSON.stringify({
      model: run.model,
      input: [
        { role: "developer", content: "# Agent instructions\n\nInspect the position. Return a **legal move** with your working notes.\nPreserve the current board until submission.\n\n## Board discipline\n\n- Use the current legal-move list.\n- Test candidates on the scratchboard.\n- Submit only after checking the opponent's reply.\n\nUse `inspect_square` to check attackers and defenders." },
        { role: "user", content: `# Canonical Position\n\nCurrent position: ${run.positionFen}\nSide to move: ${run.positionFen.split(" ")[1] === "w" ? "White" : "Black"}\n\n## Position summary\n\n| Field | Value |\n| --- | --- |\n| Source | Saved pass |\n| Board | Canonical |` },
      ],
      reasoning: { effort: "medium" }, max_output_tokens: 2000, store: false,
    }, null, 2),
    output: ["<running_thoughts>\n## Assessment\n\nThe bishop on e4 is **attacked** by the rook on e2.\nCheck the available captures before committing to a move.\n</running_thoughts>\n\n```xml\n<agent_tool_calls>\n[{\"tool\":\"inspect_square\",\"arguments\":{\"square\":\"e4\"}}]\n</agent_tool_calls>\n```", "repeated 雪", "repeated 雪"],
  };
  await page.route("**/api/positional-testing/runs?*", (route) => route.fulfill({ json: { ...saved, total: 1 } }));
  await page.route(`**/api/positional-testing/runs/${run.id}`, (route) => route.fulfill({ json: fixture }));
  await page.route("**/api/positional-testing/runs/*/passes/*/exchange", async (route) => {
    exchangeRequests++;
    if (release) await new Promise((resolve) => { release = resolve; });
    await route.fulfill(fail ? { status: 503, json: { detail: "Saved exchange temporarily unavailable" } } : { json: {
      input: long ? JSON.stringify({ input: [{ role: "user", content: "long-input ".repeat(15000) }] }) : exchange.input,
      output: empty ? [] : long ? [...exchange.output, "long-output ".repeat(15000)] : exchange.output,
    } });
  });
  await page.goto(baseUrl, { waitUntil: "networkidle" });
  await page.addStyleTag({ content: "*, *::before, *::after { animation: none !important; transition: none !important; }" });
  await page.getByRole("button", { name: "Match library", exact: true }).click();
  await page.getByRole("group", { name: "Library type" }).getByRole("button", { name: /Positional testing/ }).click();
  const pass = page.getByRole("article", { name: "Pass 2", exact: true });
  const expand = pass.getByRole("button", { name: "Expand", exact: true });
  const viewer = page.locator(".model-exchange-view");
  await expand.waitFor();
  assert.equal(exchangeRequests, 0, "History polling must not fetch full exchanges");
  assert.equal(await page.getByRole("article", { name: "Pass 4", exact: true }).getByRole("button", { name: "Expand" }).isDisabled(), true);
  await expand.scrollIntoViewIfNeeded();
  await page.getByRole("region", { name: "Model pass timeline" }).evaluate((node) => { node.scrollTop = 180; });
  await capture({ path: resolve(screenshots, "exchange-pass-desktop.png") });
  const before = await page.evaluate(() => ({ window: scrollY, timeline: document.querySelector(".run-passes").scrollTop }));
  assert.ok(before.timeline > 0, "The restoration check must exercise a scrolled pass timeline");
  await expand.click();
  await viewer.waitFor();

  const assertReadable = async () => {
    assert.deepEqual(await viewer.locator(".model-exchange-section > h1, .model-exchange-section > h2").allTextContents(), ["Input:", "Output:"]);
    assert.equal(await page.getByRole("button").count(), 1);
    assert.equal(await page.getByRole("button", { name: "Back to previous view" }).isVisible(), true);
    assert.equal(await page.getByRole("grid").count(), 0);
    assert.equal(await page.getByRole("link").count(), 0);
    assert.equal(await page.locator("body").evaluate((node) => node.innerText), await viewer.innerText());
    assert.equal(await viewer.getByRole("heading", { name: "Agent instructions", exact: true }).count(), 1);
    assert.equal(await viewer.getByRole("heading", { name: "Assessment", exact: true }).count(), 1);
    assert.equal(await viewer.locator("strong", { hasText: "legal move" }).count(), 1);
    assert.equal(await viewer.locator("table").count(), 1);
    assert.equal(await viewer.locator("li").count(), 3);
    assert.ok((await viewer.innerText()).includes("<running_thoughts>"));
    assert.ok((await viewer.innerText()).includes("</running_thoughts>"));
    assert.ok(!(await viewer.innerText()).includes('\\n'));
    assert.ok((await viewer.locator("pre").first().textContent()).includes('"max_output_tokens": 2000'));
    assert.equal(await viewer.locator("pre code.language-xml").textContent(), '<agent_tool_calls>\n[{"tool":"inspect_square","arguments":{"square":"e4"}}]\n</agent_tool_calls>\n');
    assert.deepEqual(await viewer.locator(".model-exchange-section").last().locator(".model-exchange-markdown").allTextContents(), [
      '<running_thoughts>\nAssessment\nThe bishop on e4 is attacked by the rook on e2.\nCheck the available captures before committing to a move.\n</running_thoughts>\n<agent_tool_calls>\n[{"tool":"inspect_square","arguments":{"square":"e4"}}]\n</agent_tool_calls>\n',
      "repeated 雪", "repeated 雪",
    ]);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    assert.equal(await page.evaluate(() => document.activeElement?.id), "model-input-heading");
  };
  await assertReadable();
  await capture({ path: resolve(screenshots, "exchange-markdown-desktop.png"), fullPage: true });
  await viewer.getByRole("button", { name: "Back to previous view" }).click();
  await expand.waitFor();
  await page.waitForFunction(() => document.activeElement?.textContent === "Expand");
  assert.deepEqual(await page.evaluate(() => ({ window: scrollY, timeline: document.querySelector(".run-passes").scrollTop })), before);
  await page.goForward();
  await viewer.waitFor();
  await assertReadable();
  await page.goBack();
  await expand.waitFor();
  await page.goForward();
  await viewer.waitFor();
  await page.keyboard.press("Escape");
  await expand.waitFor();

  // Network errors stay with the pass, and the same action retries successfully.
  fail = true;
  await expand.click();
  await pass.getByRole("alert").waitFor();
  assert.equal(await viewer.count(), 0);
  fail = false;
  await expand.click();
  await viewer.waitFor();
  await page.setViewportSize({ width: 390, height: 844 });
  await assertReadable();
  await capture({ path: resolve(screenshots, "exchange-markdown-mobile.png"), fullPage: true });
  await viewer.getByRole("heading", { name: "Output:", exact: true }).scrollIntoViewIfNeeded();
  assert.ok((await viewer.getByRole("button", { name: "Back to previous view" }).boundingBox()).y >= 0);
  await viewer.getByRole("button", { name: "Back to previous view" }).click();
  await expand.waitFor();
  await expand.scrollIntoViewIfNeeded();
  await capture({ path: resolve(screenshots, "exchange-pass-mobile.png") });

  // Long content remains complete and wraps to the viewport; absent output is blank.
  long = true;
  await expand.click();
  await viewer.waitFor();
  assert.ok(await viewer.locator(".model-exchange-markdown").last().textContent() === "long-output ".repeat(15000).trimEnd(), "Long output must render in full (Markdown trims trailing prose whitespace)");
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
  await page.keyboard.press("Escape");
  await expand.waitFor();
  long = false;
  empty = true;
  await expand.click();
  await viewer.waitFor();
  assert.equal(await viewer.locator(".model-exchange-section").last().innerText(), "Output:");
  await page.keyboard.press("Escape");
  await expand.waitFor();
  empty = false;

  // A direct URL survives reload; the back arrow returns locally without a pushed entry.
  const direct = new URL(`#model-pass/${run.id}/2`, baseUrl).href;
  await page.goto(direct, { waitUntil: "networkidle" });
  await page.reload({ waitUntil: "networkidle" });
  await viewer.waitFor();
  await assertReadable();
  await viewer.getByRole("button", { name: "Back to previous view" }).click();
  await page.waitForFunction(() => !location.hash);
  await page.getByRole("button", { name: "Match library", exact: true }).click();
  await page.getByRole("group", { name: "Library type" }).getByRole("button", { name: /Positional testing/ }).click();
  await expand.waitFor();

  // Leave the source screen while the request is pending; no stale viewer should open.
  release = true;
  await expand.click();
  await pass.getByRole("button", { name: "Opening…" }).waitFor();
  await page.getByRole("group", { name: "Library type" }).getByRole("button", { name: /Agent vs agent/ }).click();
  while (typeof release !== "function") await new Promise((resolve) => setTimeout(resolve, 10));
  const resume = release;
  release = null;
  const received = page.waitForResponse(/\/passes\/2\/exchange$/);
  resume();
  await received;
  await page.getByRole("group", { name: "Library type" }).getByRole("button", { name: /Positional testing/ }).click();
  await expand.waitFor();
  assert.equal(await viewer.count(), 0);
  assert.equal(new URL(page.url()).hash, "");
  assert.deepEqual(errors, []);
  console.log("Model exchange browser checks passed: lazy loading, Markdown/decoded newlines/tables/code/tags, Input/Output-only content with a back arrow, legacy/empty/error states, Back/Forward/Escape/reload, preserved scroll/focus, pending navigation, long content, desktop/mobile layouts.");
} finally {
  await browser.close();
}
