// One-off capture script for TE-16: pulls fresh screenshots + click-point
// coordinates from the *real* Fast-Flow frontend (not stale docs images).
// Not part of the shipped app — run manually against a local dev server.
import { chromium } from "playwright";
import fs from "fs";

const BASE = "http://localhost:3000";
const OUT = new URL("./public/screenshots/", import.meta.url).pathname;
const TOKEN = process.env.AUTH_TOKEN;
if (!TOKEN) {
  console.error("Set AUTH_TOKEN env var first.");
  process.exit(1);
}

fs.mkdirSync(OUT, { recursive: true });
const clickPoints = {};

const browser = await chromium.launch();
const context = await browser.newContext({
  viewport: { width: 1920, height: 1080 },
  locale: "en-US",
});
await context.addInitScript((token) => {
  window.sessionStorage.setItem("auth_token", token);
  window.localStorage.setItem("fastflow_lang", "en");
}, TOKEN);
const page = await context.newPage();

async function shot(name) {
  await page.waitForTimeout(300);
  await page.screenshot({ path: `${OUT}${name}.png` });
  console.log("captured", name);
}

// --- Dashboard ---
await page.goto(`${BASE}/`, { waitUntil: "networkidle" });
await page.waitForSelector(".stats-grid", { timeout: 15000 });
await shot("dashboard");

const dayCell = page.locator(".calendar-day:not(.empty)").last();
await dayCell.hover();
await page.waitForSelector(".calendar-tooltip", { timeout: 5000 });
const box = await dayCell.boundingBox();
clickPoints.dashboardHover = { x: box.x + box.width / 2, y: box.y + box.height / 2 };
await shot("dashboard-hover");

// --- Pipelines list ---
await page.goto(`${BASE}/pipelines`, { waitUntil: "networkidle" });
await page.waitForSelector(".pipelines-row", { timeout: 15000 });
await shot("pipelines-list");

const targetRow = page.locator(".pipelines-row", { hasText: "nightly-etl" }).first();
await targetRow.hover();
const rowBox = await targetRow.boundingBox();
clickPoints.pipelinesRowClick = { x: rowBox.x + 140, y: rowBox.y + rowBox.height / 2 };
await shot("pipelines-list-hover");

// --- Pipeline detail (result of the "click") ---
await targetRow.click();
await page.waitForURL(/\/pipelines\/nightly-etl/);
await page.waitForSelector(".pipeline-detail, [class*='pipeline-detail']", { timeout: 15000 }).catch(() => {});
await shot("pipeline-detail");

// --- Dependencies tab ---
await page.goto(`${BASE}/pipelines?section=dependencies`, { waitUntil: "networkidle" });
await page.waitForSelector(".dependencies-list, .dependencies-empty", { timeout: 15000 });
await shot("dependencies-collapsed");

const expandBtn = page.locator(".dependencies-list button").first();
const expandBox = await expandBtn.boundingBox().catch(() => null);
if (expandBox) {
  clickPoints.dependenciesExpand = {
    x: expandBox.x + expandBox.width / 2,
    y: expandBox.y + expandBox.height / 2,
  };
  await expandBtn.click();
  await page.waitForTimeout(400);
}
await shot("dependencies-expanded");

fs.writeFileSync(
  new URL("./click-points.json", import.meta.url).pathname,
  JSON.stringify(clickPoints, null, 2)
);
console.log("click points:", clickPoints);

await browser.close();
