import assert from "node:assert/strict";
import { existsSync, mkdirSync } from "node:fs";
import { resolve } from "node:path";
import { chromium } from "playwright-core";

const executablePath = [process.env.CHROME_PATH,
  "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
  "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
  "/usr/bin/chromium"].find((path) => path && existsSync(path));
assert.ok(executablePath, "A Chromium browser is required.");
const appUrl = process.argv[2] ?? "http://127.0.0.1:5174";
const directory = resolve("..", ".impeccable", "review");
mkdirSync(directory, { recursive: true });
const checkpoint = "Qwen_Qwen3-14B__project-test_train_set_1_1791485578";
const harnesses = ["Baseline", "Agent Player 1", "Agent Player 2", "Agent Player 3"].map((name, i) => ({
  id: i === 0 ? "baseline-direct-submit-langgraph-v1" : `agent-player-${i}-langgraph-v1`,
  name, version: "v1", summary: "Synthetic harness for interface verification.",
}));
const position = {
  id: "11111111-1111-4111-8111-111111111111", name: "Training position",
  datasetVersion: "v1", split: "train", phase: "middlegame", positionType: "tactical",
  source: "lichess_game", sourceGameId: "synthetic", sourceUrl: "https://lichess.org",
  opening: null, themes: [], puzzleRating: null, sideToMove: "white", moveCount: 38,
  position: { ply: 38, fen: "r1b1r1k1/pp3ppp/5q2/3p4/1P1P1B2/P2Q3P/5PP1/2R2RK1 w - - 1 20", san: "", player: "black", fromSquare: null, toSquare: null },
};
const browser = await chromium.launch({ executablePath, headless: true });
try {
  for (const viewport of [{ name: "desktop", width: 1440, height: 1000 }, { name: "mobile", width: 390, height: 844 }]) {
    const page = await browser.newPage({ viewport });
    let inventory = [checkpoint];
    let inventoryError = null;
    let releaseRun;
    const requests = [];
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.route((url) => url.pathname.startsWith("/api/"), async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      const path = url.pathname;
      const send = (body, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
      if (path === "/api/models") {
        const server = url.searchParams.get("server");
        return server === "unsloth" && inventoryError ? send({ detail: inventoryError }, 503)
          : send({ server, models: server === "unsloth" ? inventory : ["qwen3-14b"] });
      }
      if (path === "/api/harnesses") return send(harnesses);
      if (path === "/api/folders") return send({ items: [], totalMatches: 0, unfiledCount: 0 });
      if (path === "/api/matches" && request.method() === "GET") return send({ items: [], total: 0 });
      if (path === "/api/positional-testing/positions") return send({ items: [position] });
      if (path === "/api/positional-testing/queues") return send({ items: [] });
      if (path === "/api/positional-testing/runs" && request.method() === "GET") return send({ items: [], total: 0 });
      if (request.method() === "POST") {
        requests.push({ path, body: request.postDataJSON() });
        if (path === "/api/matches") return send({ detail: "Synthetic match request verified." }, 503);
        if (path === "/api/positional-testing/runs") {
          await new Promise((resolveRun) => { releaseRun = resolveRun; });
          return send({ runId: "synthetic-run", positionId: position.id, positionName: position.name,
            harnessId: harnesses[2].id, harnessName: harnesses[2].name, harnessVersion: "v1", model: checkpoint,
            side: "white", ply: 38, move: {san: "Be5", uci: "f4e5", fromSquare: "f4", toSquare: "e5"},
            justification: "Synthetic response used only to verify the interface.", defenseReport: null, attackReport: null });
        }
      }
      throw new Error(`Unexpected ${request.method()} ${path}`);
    });
    await page.goto(appUrl, { waitUntil: "networkidle" });
    const server = page.getByRole("combobox", { name: "Model server", exact: true });
    const loaded = page.getByRole("combobox", { name: "Loaded model", exact: true });
    await loaded.selectOption("qwen3-14b");
    await server.selectOption("unsloth");
    await loaded.locator(`option[value="${checkpoint}"]`).waitFor({ state: "attached" });
    await page.waitForFunction(() => document.querySelector("#model-routing-status")?.textContent.includes("Unsloth · 1 loaded"));
    assert.equal(await loaded.inputValue(), checkpoint);
    await page.getByRole("combobox", { name: "White harness" }).selectOption(harnesses[2].id);
    await page.getByRole("combobox", { name: "Black harness" }).selectOption(harnesses[2].id);
    await page.getByRole("button", { name: "Start match", exact: true }).click();
    await page.getByText("Backend request failed. Synthetic match request verified.", { exact: true }).waitFor();
    assert.deepEqual(requests.at(-1).body.modelSelection, { modelId: "unsloth", reasoningEffort: "medium", modelName: checkpoint });

    inventoryError = "Unsloth authentication failed. Check the backend access token.";
    await page.getByRole("button", { name: "Refresh loaded models" }).click();
    await page.getByText(inventoryError, { exact: true }).waitFor();
    assert.ok(await page.getByRole("button", { name: "Start match", exact: true }).isDisabled());
    inventoryError = null;
    inventory = [];
    await page.getByRole("button", { name: "Refresh loaded models" }).click();
    await page.getByText("No model loaded. Load one in your server, then refresh.").waitFor();
    assert.ok(await page.getByRole("button", { name: "Start match", exact: true }).isDisabled());
    inventory = ["second-checkpoint"];
    await page.getByRole("button", { name: "Refresh loaded models" }).click();
    await page.getByText("Selected model is no longer loaded. Choose a model or refresh.").waitFor();
    assert.equal(await loaded.inputValue(), checkpoint);
    inventory = [checkpoint, "second-checkpoint"];
    await page.getByRole("button", { name: "Refresh loaded models" }).click();
    await loaded.selectOption(checkpoint);
    await page.getByRole("button", { name: "Positional testing", exact: true }).click();
    await page.getByRole("button", { name: /Training position/ }).click();
    await page.locator(`input[value="${harnesses[2].id}"]`).check();
    const run = page.getByRole("button", { name: /Run once|Run again/, exact: true });
    await run.click();
    await page.getByRole("button", { name: /^Running one turn/ }).waitFor();
    assert.ok(await server.isDisabled());
    assert.ok(await loaded.isDisabled());
    assert.equal(requests.at(-1).body.harnessId, harnesses[2].id);
    assert.equal(requests.at(-1).body.modelSelection.modelName, checkpoint);
    releaseRun();
    await page.getByRole("button", { name: "Run again", exact: true }).waitFor();
    assert.ok(await server.isEnabled());
    await page.evaluate(() => window.scrollTo(0, 0));
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), "Horizontal overflow");
    await page.screenshot({ path: resolve(directory, `unsloth-${viewport.name}.png`), fullPage: true });
    await server.selectOption("gpt-terra");
    await page.getByRole("combobox", { name: "Requested model", exact: true }).waitFor();
    assert.equal(await page.getByRole("combobox", { name: "Requested model", exact: true }).inputValue(), "gpt-terra");
    await page.getByRole("button", { name: "Match desk", exact: true }).click();
    for (const [modelId, modelName, harness] of [["gpt-terra", undefined, harnesses[3]], ["qwen", "qwen3-14b", harnesses[2]]]) {
      await server.selectOption(modelId);
      await page.getByRole("combobox", { name: "White harness" }).selectOption(harness.id);
      await page.getByRole("combobox", { name: "Black harness" }).selectOption(harness.id);
      const response = page.waitForResponse((item) => new URL(item.url()).pathname === "/api/matches" && item.request().method() === "POST");
      await page.getByRole("button", { name: "Start match", exact: true }).click();
      await response;
      assert.deepEqual(requests.at(-1).body.modelSelection, { modelId, reasoningEffort: "medium", ...(modelName ? { modelName } : {}) });
    }
    assert.deepEqual(errors, []);
    console.log(`${viewport.name}: server switching, exact checkpoint, match/single-run payloads, failures, empty/unloaded models, disabled states, and layout passed`);
    await page.close();
  }
} finally { await browser.close(); }
