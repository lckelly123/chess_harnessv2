import { existsSync, mkdirSync } from "node:fs";
import { resolve } from "node:path";
import { chromium } from "playwright-core";

const executableCandidates = [
  process.env.CHROME_PATH,
  "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
  "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
  "/usr/bin/google-chrome",
  "/usr/bin/chromium",
].filter(Boolean);

const executablePath = executableCandidates.find((candidate) => existsSync(candidate));
if (!executablePath) throw new Error("Set CHROME_PATH to a Chromium-based browser executable.");

const appUrl = process.argv[2] ?? process.env.APP_URL ?? "http://127.0.0.1:5173";
const reviewDirectory = resolve("..", ".impeccable", "review");
mkdirSync(reviewDirectory, { recursive: true });

const browser = await chromium.launch({ executablePath, headless: true });
const runResponse = {
  runId: "positional-test-review",
  positionId: "before_queen_blunder",
  positionName: "Agent Player 1 Queen Blunder Test",
  harnessId: "agent-player-1-langgraph-v1",
  harnessName: "Agent Player 1",
  harnessVersion: "agent-player-1-langgraph-v1",
  model: "qwen3-30b-a3b-instruct-2507",
  side: "black",
  ply: 23,
  move: {
    san: "Qxe3+",
    uci: "d4e3",
    fromSquare: "d4",
    toSquare: "e3",
    promotion: null,
    isCapture: true,
    givesCheck: true,
    isCastling: false,
    isEnPassant: false,
  },
  justification: "The queen wins the bishop on e3 with check while preserving the initiative.",
  defenseReport: "No immediate defensive obligation outweighs the forcing capture.",
  attackReport: "Qxe3+ is a forcing capture that checks the king and wins material.",
};

for (const viewport of [
  { name: "positional-desktop", width: 1440, height: 1000 },
  { name: "positional-mobile", width: 390, height: 844 },
]) {
  const page = await browser.newPage({ viewport });
  let runCalls = 0;
  await page.route("**/api/positional-testing/runs", async (route) => {
    runCalls += 1;
    await new Promise((resolveDelay) => setTimeout(resolveDelay, 250));
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(runResponse),
    });
  });
  await page.goto(appUrl, { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "Positional testing" }).click();
  await page.getByRole("button", { name: /Agent Player 1 Queen Blunder Test/ }).click();

  const baseline = page.locator('input[value="baseline-direct-submit-langgraph-v1"]');
  const agentPlayer = page.locator('input[value="agent-player-1-langgraph-v1"]');
  await baseline.check();
  if (!(await baseline.isChecked())) throw new Error("Baseline selection did not persist.");
  await agentPlayer.check();
  if (!(await agentPlayer.isChecked())) throw new Error("Agent Player 1 selection did not persist.");
  await page.getByRole("button", { name: "Run once" }).click();
  if (viewport.name === "positional-desktop") {
    await page.getByRole("button", { name: "Match desk" }).click();
    await page.getByRole("button", { name: "Positional testing" }).click();
    await page.getByRole("button", { name: "Running one turn…" }).waitFor();
  }
  await page.getByRole("heading", { name: "Proposed move" }).waitFor();
  if (runCalls !== 1) throw new Error(`Expected one positional run, received ${runCalls}.`);
  await page.getByText("Qxe3+").first().waitFor();
  if (await page.locator(".board-square").count() !== 64) {
    throw new Error("The selected saved position did not render a complete board.");
  }
  await page.evaluate(() => window.scrollTo(0, 0));

  await page.screenshot({
    path: resolve(reviewDirectory, `${viewport.name}.png`),
    fullPage: true,
    animations: "disabled",
  });
  await page.close();
}

const unavailablePage = await browser.newPage({ viewport: { width: 390, height: 844 } });
await unavailablePage.route("**/api/harnesses", (route) =>
  route.fulfill({
    status: 503,
    contentType: "application/json",
    body: JSON.stringify({ detail: "Harness catalog unavailable." }),
  }),
);
await unavailablePage.goto(appUrl, { waitUntil: "networkidle" });
await unavailablePage.getByRole("button", { name: "Positional testing" }).click();
await unavailablePage.getByRole("button", { name: /Agent Player 1 Queen Blunder Test/ }).click();
await unavailablePage.getByText("Harness choices unavailable.").waitFor();
await unavailablePage.getByRole("button", { name: "Retry" }).waitFor();
await unavailablePage.locator(".agent-picker").screenshot({
  path: resolve(reviewDirectory, "positional-mobile-model-error.png"),
  animations: "disabled",
});
await unavailablePage.close();

const missingHarnessPage = await browser.newPage({ viewport: { width: 390, height: 844 } });
await missingHarnessPage.route("**/api/harnesses", (route) =>
  route.fulfill({
    contentType: "application/json",
    body: JSON.stringify([
      {
        id: "baseline-direct-submit-langgraph-v1",
        name: "Baseline",
        version: "baseline-direct-submit-langgraph-v1",
        summary: "Direct legal move submission through a two-node LangGraph.",
      },
    ]),
  }),
);
await missingHarnessPage.goto(appUrl, { waitUntil: "networkidle" });
await missingHarnessPage.getByRole("button", { name: "Positional testing" }).click();
await missingHarnessPage.getByRole("button", { name: /Agent Player 1 Queen Blunder Test/ }).click();
await missingHarnessPage.getByText("Expected harness missing.").waitFor();
await missingHarnessPage.getByText(/Agent Player 1/).last().waitFor();
await missingHarnessPage.getByRole("button", { name: "Reload harnesses" }).waitFor();
await missingHarnessPage.locator(".agent-picker").screenshot({
  path: resolve(reviewDirectory, "positional-mobile-missing-model.png"),
  animations: "disabled",
});
await missingHarnessPage.close();

const runErrorPage = await browser.newPage({ viewport: { width: 390, height: 844 } });
await runErrorPage.route("**/api/positional-testing/runs", (route) =>
  route.fulfill({
    status: 503,
    contentType: "application/json",
    body: JSON.stringify({ detail: "LM Studio has no loaded language model." }),
  }),
);
await runErrorPage.goto(appUrl, { waitUntil: "networkidle" });
await runErrorPage.getByRole("button", { name: "Positional testing" }).click();
await runErrorPage.getByRole("button", { name: /Agent Player 1 Queen Blunder Test/ }).click();
await runErrorPage.locator('input[value="agent-player-1-langgraph-v1"]').check();
await runErrorPage.getByRole("button", { name: "Run once" }).click();
await runErrorPage.getByText("The agent did not return a move.").waitFor();
await runErrorPage.getByRole("button", { name: "Try again" }).waitFor();
await runErrorPage.locator(".position-stage").screenshot({
  path: resolve(reviewDirectory, "positional-mobile-run-error.png"),
  animations: "disabled",
});
await runErrorPage.close();

await browser.close();
