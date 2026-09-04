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

const reviewDirectory = resolve("..", ".impeccable", "review");
mkdirSync(reviewDirectory, { recursive: true });

const browser = await chromium.launch({ executablePath, headless: true });

for (const viewport of [
  { name: "desktop", width: 1440, height: 1000 },
  { name: "mobile", width: 390, height: 844 },
]) {
  const page = await browser.newPage({ viewport });
  await page.goto("http://localhost:5173", { waitUntil: "networkidle" });
  await page.locator(".match-workspace").waitFor({ state: "visible" });
  await page.screenshot({
    path: resolve(reviewDirectory, `${viewport.name}.png`),
    fullPage: true,
    animations: "disabled",
  });
  await page.close();
}

await browser.close();
