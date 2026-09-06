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

const folderFixture = {
  id: "folder-visual-check",
  name: "Baseline comparisons",
  createdAt: "2026-09-05T20:00:00Z",
  matchCount: 0,
};

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

const emptyFolderPage = await browser.newPage({ viewport: { width: 390, height: 844 } });
await emptyFolderPage.route("**/api/folders", (route) =>
  route.fulfill({
    contentType: "application/json",
    body: JSON.stringify({
      items: [folderFixture],
      totalMatches: 3,
      unfiledCount: 3,
    }),
  }),
);
await emptyFolderPage.route("**/api/matches?**", (route) => {
  const url = new URL(route.request().url());
  if (url.searchParams.get("folder_id") === folderFixture.id) {
    return route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ items: [], total: 0 }),
    });
  }
  return route.continue();
});
await emptyFolderPage.goto("http://localhost:5173", { waitUntil: "networkidle" });
await emptyFolderPage.getByRole("button", { name: /Baseline comparisons/ }).click();
await emptyFolderPage.getByText("This folder is empty.", { exact: false }).waitFor();
await emptyFolderPage.locator(".records-workspace").screenshot({
  path: resolve(reviewDirectory, "mobile-empty-folder.png"),
  animations: "disabled",
});
await emptyFolderPage.close();

const assignmentPage = await browser.newPage({ viewport: { width: 390, height: 844 } });
await assignmentPage.route("**/api/folders", (route) =>
  route.fulfill({
    contentType: "application/json",
    body: JSON.stringify({
      items: [folderFixture],
      totalMatches: 3,
      unfiledCount: 3,
    }),
  }),
);
await assignmentPage.route("**/api/matches/*/folder", (route) =>
  route.fulfill({
    status: 503,
    contentType: "application/json",
    body: JSON.stringify({ detail: "Could not move this record. Try again." }),
  }),
);
await assignmentPage.goto("http://localhost:5173", { waitUntil: "networkidle" });
const firstAssignment = assignmentPage.locator(".history-folder-control select").first();
await firstAssignment.selectOption(folderFixture.id);
await assignmentPage.getByText("Could not move this record. Try again.").waitFor();
await assignmentPage.locator(".history-row").first().screenshot({
  path: resolve(reviewDirectory, "mobile-assignment-error.png"),
  animations: "disabled",
});
await assignmentPage.close();

await browser.close();
