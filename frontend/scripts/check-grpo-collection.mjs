// Every API request is mocked. This never runs a model or touches collection files.
import assert from "node:assert/strict";
import { existsSync, mkdirSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { chromium } from "playwright-core";

const executablePath = [process.env.CHROME_PATH, "C:/Program Files/Google/Chrome/Application/chrome.exe", "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", "/usr/bin/chromium"].find((path) => path && existsSync(path));
assert.ok(executablePath, "A Chromium browser is required.");
const directory = resolve("../.impeccable/review");
mkdirSync(directory, { recursive: true });
const checkpoint = "Qwen_Qwen3-14B__project-true_trial_v1.2_1792812112";
const position = {
  id: "00000000-0000-4000-8000-000000000001", name: "Middlegame · move 20", datasetVersion: "v1", split: "train", phase: "middlegame", positionType: "quiet", sideToMove: "white", moveCount: 38,
  source: "lichess_game", sourceGameId: "fixture", sourceUrl: "https://lichess.org/0wtBizME", opening: "Alekhine Defense: Exchange Variation", themes: [], puzzleRating: null,
  position: { ply: 38, fen: "r1b1r1k1/pp3ppp/5q2/3p4/1P1P1B2/P2Q3P/5PP1/2R2RK1 w - - 1 20", san: "Qf6", player: "black", fromSquare: "d8", toSquare: "f6" },
};
const harnesses = ["Baseline", "legacy", "chess_harness", "chess_charness_alt"].map((name, i) => ({ id: i ? `agent-player-${i}-langgraph-v1` : "baseline-direct-submit-langgraph-v1", name, version: "v1", summary: "Browser fixture" }));
const browser = await chromium.launch({ executablePath, headless: true });
try {
  for (const viewport of [{ name: "desktop", width: 1440, height: 1000 }, { name: "mobile", width: 390, height: 844 }]) {
    const page = await browser.newPage({ viewport });
    page.setDefaultTimeout(12000);
    const errors = [];
    const mutations = [];
    page.on("pageerror", (error) => errors.push(error.message));
    let workerOnline = false;
    let statusError = false;
    let group = null;
    let rejectStart = true;
    let rejectStop = true;
    let unloaded = false;
    const active = () => group && ["preparing", "running"].includes(group.status);
    // Serve the built app from intercepted requests; no loopback/network permission needed.
    await page.route("**/*", async (route) => {
      const path = new URL(route.request().url()).pathname;
      const file = resolve("dist", path === "/" ? "index.html" : `.${path}`);
      assert.ok(file.startsWith(resolve("dist")) && existsSync(file), `Unexpected asset: ${path}`);
      const contentType = path.endsWith(".js") ? "text/javascript" : path.endsWith(".css") ? "text/css" : path.endsWith(".woff2") ? "font/woff2" : "text/html";
      return route.fulfill({ contentType, body: readFileSync(file) });
    });
    await page.route((url) => url.pathname.startsWith("/api/"), async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      const path = url.pathname;
      const send = (json, status = 200) => route.fulfill({ json, status });
      if (path === "/api/grpo/status") return statusError ? send({ detail: "Temporary connection failure." }, 503) : send({ workerOnline, workerMessage: workerOnline ? null : "Start the GRPO capture worker, then retry.", activeRun: active() ? group : null });
      if (path === "/api/grpo/runs" && request.method() === "POST") {
        mutations.push({ path, body: request.postDataJSON() });
        if (rejectStart) { rejectStart = false; return send({ detail: "That run folder already exists. Choose another name." }, 409); }
        const body = request.postDataJSON();
        assert.equal(body.positionId, position.id);
        assert.equal(body.harnessId, harnesses[2].id);
        assert.equal(body.modelSelection.modelName, checkpoint);
        group = { name: body.name, status: "preparing", positionId: position.id, harnessId: harnesses[2].id, modelName: checkpoint, currentTrajectory: null, currentCall: 0, completedTrajectories: 0, totalTrajectories: 10, outputDirectory: `C:\\Repos\\chess_harness_v2\\chess_harnessv2\\models\\training_data\\RL_testing\\${body.name}`, stopping: false, error: null, trajectories: Array.from({ length: 10 }, (_, i) => ({ trajectory: i + 1, status: "pending", cpLoss: null, rejectedModelCalls: 0, toolCounts: {} })) };
        return send(group, 202);
      }
      if (path.endsWith("/stop") && path.startsWith("/api/grpo/runs/") && request.method() === "POST") {
        mutations.push({ path });
        if (rejectStop) { rejectStop = false; return send({ detail: "Temporary stop failure. Try again." }, 503); }
        group.stopping = true;
        return send(group);
      }
      if (path.startsWith("/api/grpo/runs/") && request.method() === "GET") return send(group);
      assert.equal(request.method(), "GET", `Unexpected mutation: ${path}`);
      if (path === "/api/models") return send({ server: url.searchParams.get("server"), models: unloaded ? [] : [checkpoint] });
      if (path === "/api/harnesses") return send(harnesses);
      if (path === "/api/folders") return send({ items: [], totalMatches: 0, unfiledCount: 0 });
      if (path === "/api/matches") return send({ items: [], total: 0 });
      if (path === "/api/codex-training/worker") return send({ configured: true, online: false, model: null, reasoning_effort: null, active_run_id: null, active_queue_id: null });
      if (path === "/api/positional-testing/positions") return send({ items: [position] });
      if (path === "/api/positional-testing/queues") return send({ items: [] });
      if (path === "/api/positional-testing/run-filters") return send({ datasets: ["v1"], models: [], harnesses, queues: [] });
      if (path === "/api/positional-testing/runs") return send({ items: [], total: 0 });
      throw new Error(`Unexpected request: ${path}`);
    });
    const goToPosition = async () => {
      await page.goto("http://grpo-fixture.test/", { waitUntil: "networkidle" });
      await page.getByRole("button", { name: "Positional testing", exact: true }).click();
    };
    await goToPosition();
    const toggle = page.getByRole("checkbox", { name: "Save for GRPO", exact: false });
    assert.ok(await toggle.isDisabled(), "Requires eligible model and harness");
    await page.getByRole("combobox", { name: "Model server", exact: true }).selectOption("unsloth");
    await page.getByRole("radio", { name: /chess_harness/ }).check();
    await toggle.check();
    const run = page.getByRole("button", { name: "Run 10 trajectories", exact: true });
    assert.equal(await page.getByRole("button", { name: "Run once", exact: true }).count(), 0);
    await page.getByText("Start the GRPO capture worker, then retry.", { exact: true }).waitFor();
    assert.ok(await run.isDisabled());
    workerOnline = true;
    await page.getByText(/Capture worker ready/).waitFor();
    const input = page.getByRole("textbox", { name: "Run name", exact: true });
    assert.ok(await run.isDisabled(), "Run name is required");
    await input.fill("../escape");
    assert.equal(await input.getAttribute("aria-invalid"), "true");
    assert.ok(await run.isDisabled());
    await input.fill("CON");
    assert.ok(await run.isDisabled());
    await input.fill("XYZ");
    await input.press("Tab");
    await run.scrollIntoViewIfNeeded();
    await page.screenshot({ path: resolve(directory, `grpo-ready-${viewport.name}.png`) });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), "No horizontal page overflow");
    await run.click();
    await page.getByRole("alert").filter({ hasText: "That run folder already exists." }).waitFor();
    await input.fill("XYZ-new");
    await run.click();
    await page.getByText("Preparing collection", { exact: true }).waitFor();
    assert.ok(await toggle.isDisabled());
    assert.ok(await input.isDisabled());
    group.status = "running";
    group.currentTrajectory = 3;
    group.currentCall = 12;
    group.completedTrajectories = 2;
    group.trajectories[0].status = "completed";
    group.trajectories[1].status = "failed";
    group.trajectories[2].status = "running";
    await page.getByText("Trajectory 3/10 · Model call 12", { exact: true }).waitFor();
    unloaded = true;
    await goToPosition();
    await page.getByText("Trajectory 3/10 · Model call 12", { exact: true }).waitFor();
    assert.ok(await toggle.isChecked(), "Reload reattaches active GRPO collection despite unloaded Studio model");
    const stop = page.getByRole("button", { name: "Stop collection", exact: true });
    assert.ok(await stop.isEnabled());
    await stop.scrollIntoViewIfNeeded();
    await page.screenshot({ path: resolve(directory, `grpo-active-${viewport.name}.png`) });
    statusError = true;
    await page.getByRole("alert").filter({ hasText: "Connection interrupted." }).waitFor();
    assert.ok(await stop.isEnabled(), "Lost polling connection does not hide stop");
    statusError = false;
    await page.getByRole("button", { name: "Retry", exact: true }).click();
    await page.waitForFunction(() => !document.querySelector(".grpo-collection__connection"));
    await stop.click();
    await page.getByRole("alert").filter({ hasText: "Temporary stop failure." }).waitFor();
    await page.getByRole("button", { name: "Retry stop collection", exact: true }).click();
    await page.getByText("Stopping collection", { exact: true }).waitFor();
    assert.ok(await page.getByRole("button", { name: "Stopping…", exact: true }).last().isDisabled());
    group.status = "stopped";
    group.stopping = false;
    group.trajectories[2].status = "stopped";
    await page.getByText("Collection stopped", { exact: true }).waitFor();
    await page.getByText("Captured files have been kept.", { exact: true }).waitFor();
    await toggle.uncheck();
    await page.getByRole("button", { name: "Run once", exact: true }).waitFor();
    assert.equal(mutations.length, 4, "Only expected create and stop commands were issued");
    assert.ok(mutations.every((mutation) => mutation.path.startsWith("/api/grpo/")), "Never use ordinary discard for GRPO");
    assert.deepEqual(errors, []);
    await page.close();
  }
  console.log("GRPO UI passed: eligibility, naming, offline readiness, conflict retry, progress, reload with unloaded model, reconnect and stop/retry preserving files at desktop/mobile widths.");
} finally { await browser.close(); }
