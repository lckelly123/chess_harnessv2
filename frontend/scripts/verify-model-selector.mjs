import assert from "node:assert/strict";
import { existsSync, mkdirSync } from "node:fs";
import { resolve } from "node:path";
import { chromium } from "playwright-core";

const executablePath = [
  process.env.CHROME_PATH,
  "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
  "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
  "/usr/bin/google-chrome",
  "/usr/bin/chromium",
].find((path) => path && existsSync(path));
assert.ok(executablePath, "Set CHROME_PATH to a Chromium-based browser executable.");

const appUrl = process.argv[2] ?? "http://127.0.0.1:5174";
const reviewDirectory = resolve("..", ".impeccable", "review");
mkdirSync(reviewDirectory, { recursive: true });
const harnesses = [
  { id: "baseline-direct-submit-langgraph-v1", name: "Baseline", summary: "Direct legal move submission." },
  { id: "agent-player-1-langgraph-v1", name: "Agent Player 1", summary: "Defense, attack, and synthesis." },
  { id: "agent-player-2-langgraph-v1", name: "Agent Player 2", summary: "Single synthesis phase." },
].map((harness) => ({ ...harness, version: harness.id }));
const position = {
  id: "before_queen_blunder",
  name: "Agent Player 1 Queen Blunder Test",
  sourceFile: "before_queen_blunder.pgn",
  white: "Baseline",
  black: "Agent Player 1",
  sideToMove: "black",
  moveCount: 23,
  position: {
    ply: 23,
    fen: "2r1kb1r/p1p1pppp/2p5/8/3q4/2N1B3/PPP2PPP/R3K2R b KQk - 1 12",
    san: "Be3",
    player: "white",
    fromSquare: "c1",
    toSquare: "e3",
  },
};
const runResult = {
  runId: "positional-test-ui-fixture",
  positionId: position.id,
  positionName: position.name,
  harnessId: harnesses[2].id,
  harnessName: harnesses[2].name,
  harnessVersion: harnesses[2].version,
  model: "unsloth/qwen3.8-27b",
  side: "black",
  ply: 23,
  move: { san: "Qb4", uci: "d4b4", fromSquare: "d4", toSquare: "b4" },
  justification: "Synthetic response for frontend interaction verification.",
  defenseReport: null,
  attackReport: null,
};
const browser = await chromium.launch({ executablePath, headless: true });
const results = [];

try {
  for (const viewport of [
    { name: "desktop", width: 1440, height: 1000 },
    { name: "mobile", width: 390, height: 844 },
  ]) {
    const page = await browser.newPage({ viewport });
    const requests = [];
    const errors = [];
    let releaseRun;
    page.on("pageerror", (error) => errors.push(error.message));
    await page.route((url) => url.pathname.startsWith("/api/"), async (route) => {
      const request = route.request();
      const path = new URL(request.url()).pathname;
      const respond = (body, status = 200) => route.fulfill({
        status,
        contentType: "application/json",
        body: JSON.stringify(body),
      });
      if (path === "/api/harnesses") return respond(harnesses);
      if (path === "/api/folders") return respond({ items: [], totalMatches: 0, unfiledCount: 0 });
      if (path === "/api/matches" && request.method() === "GET") return respond({ items: [], total: 0 });
      if (path === "/api/positional-testing/positions") return respond({ items: [position] });
      if (request.method() === "POST") {
        requests.push({ path, body: request.postDataJSON() });
        if (path === "/api/matches") {
          return respond({ detail: "Synthetic match response; no match was started." }, 503);
        }
        if (path === "/api/positional-testing/runs") {
          await new Promise((resolveRun) => { releaseRun = resolveRun; });
          return respond(runResult);
        }
      }
      throw new Error(`Unexpected request: ${request.method()} ${path}`);
    });

    await page.goto(appUrl, { waitUntil: "networkidle" });
    const selector = page.getByRole("combobox", { name: "Requested model" });
    assert.equal(await selector.inputValue(), "qwen");
    assert.deepEqual(await selector.locator("option").allTextContents(), ["Qwen", "GPT Luna"]);
    assert.equal(await page.locator(".model-settings__reasoning dd").innerText(), "Medium");
    await page.getByText("LM Studio", { exact: true }).waitFor();

    for (const modelId of ["qwen", "gpt-luna"]) {
      await selector.selectOption(modelId);
      assert.equal(await page.locator("#model-routing-status").innerText(), modelId === "gpt-luna" ? "OpenAI API" : "LM Studio");
      await page.getByRole("button", { name: "Start match", exact: true }).click();
      await page.getByText("Synthetic match response; no match was started.", { exact: false }).waitFor();
      assert.deepEqual(requests.at(-1), {
        path: "/api/matches",
        body: {
          whiteHarnessId: harnesses[0].id,
          blackHarnessId: harnesses[1].id,
          folderId: null,
          modelSelection: { modelId, reasoningEffort: "medium" },
        },
      });
      assert.equal(await selector.isEnabled(), true);
    }

    await page.getByRole("button", { name: "Positional testing", exact: true }).click();
    assert.equal(await selector.inputValue(), "gpt-luna");
    await page.getByRole("button", { name: /Agent Player 1 Queen Blunder Test/ }).click();
    await page.locator(`input[value="${harnesses[2].id}"]`).check();
    assert.equal(await page.locator(".board-square").count(), 64);

    for (const modelId of ["gpt-luna", "qwen"]) {
      await selector.selectOption(modelId);
      await page.getByRole("button", { name: /Run once|Run again/, exact: true }).click();
      await page.getByRole("button", { name: /^Running one turn/ }).waitFor();
      assert.equal(await selector.isDisabled(), true);
      await page.getByRole("button", { name: "Match desk", exact: true }).click();
      assert.equal(await selector.isDisabled(), true);
      await page.getByRole("button", { name: "Positional testing", exact: true }).click();
      assert.deepEqual(requests.at(-1), {
        path: "/api/positional-testing/runs",
        body: {
          positionId: position.id,
          harnessId: harnesses[2].id,
          modelSelection: { modelId, reasoningEffort: "medium" },
        },
      });
      assert.equal(typeof releaseRun, "function");
      releaseRun();
      await page.getByRole("heading", { name: "Proposed move", exact: true }).waitFor();
      assert.equal(await selector.isEnabled(), true);
      await page.getByText(runResult.model, { exact: true }).waitFor();
    }

    await selector.selectOption("gpt-luna");
    await selector.focus();
    assert.notEqual(await selector.evaluate((element) => getComputedStyle(element).outlineStyle), "none");
    await page.evaluate(async () => {
      await document.fonts.ready;
      document.documentElement.style.scrollBehavior = "auto";
      window.scrollTo({ top: 0, behavior: "instant" });
    });
    await page.waitForFunction(() => window.scrollY === 0);
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), "Horizontal overflow");
    const boxes = await page.locator(".model-settings > *").evaluateAll((elements) => elements.map((element) => {
      const { x, y, width, height } = element.getBoundingClientRect();
      return { x, y, width, height };
    }));
    for (let a = 0; a < boxes.length; a++) {
      for (let b = a + 1; b < boxes.length; b++) {
        const first = boxes[a];
        const second = boxes[b];
        assert.ok(first.x + first.width <= second.x || second.x + second.width <= first.x
          || first.y + first.height <= second.y || second.y + second.height <= first.y, "Model controls overlap");
      }
    }
    await page.screenshot({ path: resolve(reviewDirectory, `model-selector-${viewport.name}.png`), fullPage: true, animations: "disabled" });
    assert.deepEqual(errors, []);
    assert.equal(requests.length, 4);
    results.push({ viewport: viewport.name, requests: requests.length, errors, layout: "passed" });
    await page.close();
  }
} finally {
  await browser.close();
}

console.log(JSON.stringify(results, null, 2));
