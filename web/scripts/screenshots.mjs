// Click through the full mock flow and capture screenshots for design review.
// Usage: npm run dev (in another shell), then: node scripts/screenshots.mjs [baseUrl]
// Needs playwright-core + a cached Chromium (~/.cache/ms-playwright/chromium-*).
import { chromium } from "playwright-core";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const BASE = process.argv[2] ?? "http://localhost:5173";
const OUT = path.resolve(path.dirname(new URL(import.meta.url).pathname), "../screenshots");
fs.mkdirSync(OUT, { recursive: true });

function findChromium() {
  const root = path.join(os.homedir(), ".cache/ms-playwright");
  const dirs = fs.existsSync(root) ? fs.readdirSync(root).filter((d) => /^chromium-\d+$/.test(d)).sort() : [];
  for (const d of dirs.reverse()) {
    const p = path.join(root, d, "chrome-linux64/chrome");
    if (fs.existsSync(p)) return p;
  }
  return undefined;
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const errors = [];

async function shot(page, name, opts = {}) {
  const file = path.join(OUT, `${name}.png`);
  await page.screenshot({ path: file, ...opts });
  console.log("saved", path.relative(process.cwd(), file));
}

async function desktop(browser) {
  const ctx = await browser.newContext({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 });
  const page = await ctx.newPage();
  page.on("console", (m) => m.type() === "error" && errors.push(`[desktop] ${m.text()}`));
  page.on("pageerror", (e) => errors.push(`[desktop] ${e.message}`));

  await page.goto(`${BASE}/?mock=1#/`);
  await page.waitForSelector("text=Split the bill");
  await sleep(600);
  await shot(page, "d01-home");

  await page.click("button:has-text('Split the bill')");
  await page.click("button[type=submit]:has-text('Fork it')");
  await sleep(1300);
  await shot(page, "d02-frame");
  await sleep(3200);
  await shot(page, "d03-fanout");
  await sleep(3400);
  await shot(page, "d04-execute");
  await sleep(2200);
  await shot(page, "d05-cluster");
  await page.waitForSelector("text=Lock it in", { timeout: 20000 });
  await sleep(1500);
  await shot(page, "d06-meanings");
  await shot(page, "d06-meanings-full", { fullPage: true });

  // Answer Q1 (first option) and Q2 (first option).
  const radios = page.locator("[role=radiogroup] label");
  await radios.nth(0).click();
  await sleep(500);
  await shot(page, "d07-answer-q1");
  await page.locator("section:has-text('nobody to split') [role=radiogroup] label").first().click();
  await sleep(400);
  await page.locator("text=Lock it in").scrollIntoViewIfNeeded();
  await shot(page, "d08-ready-to-lock");

  await page.click("button:has-text('Lock it in')");
  await sleep(700);
  await shot(page, "d09-resolving");
  await page.waitForSelector("text=Clarified spec", { timeout: 15000 });
  await sleep(1800);
  await shot(page, "d10-resolved");

  await page.click("button:has-text('Re-fork clarified spec')");
  await sleep(2600);
  await shot(page, "d11-converging");
  await page.waitForSelector("text=Re-fork again", { timeout: 20000 });
  await sleep(1800);
  await shot(page, "d12-converged");
  await shot(page, "d12-converged-full", { fullPage: true });

  await page.locator("text=tests.py").first().scrollIntoViewIfNeeded();
  await sleep(300);
  await shot(page, "d13-tests-tab");

  await page.evaluate(() => window.scrollTo(0, 0));
  await page.click("button:has-text('Inspect')");
  await sleep(700);
  await page.locator("button[aria-label^='Show details for frame']").click();
  await sleep(400);
  await shot(page, "d14-trace");
  await page.keyboard.press("Escape");
  await sleep(500);

  await page.locator("[aria-label^='Implementation #2:']").first().click();
  await sleep(700);
  await shot(page, "d15-impl-drawer");
  await page.keyboard.press("Escape");
  await sleep(400);

  await page.click("button:has-text('How it works')");
  await sleep(600);
  await shot(page, "d16-how-it-works");
  await page.keyboard.press("Escape");

  await page.goto(`${BASE}/?mock=1#/run/sample-bill-split`);
  await page.waitForSelector("text=Recorded run");
  await sleep(1500);
  await shot(page, "d17-sample-run");

  // Validation state.
  await page.goto(`${BASE}/?mock=1#/`);
  await page.waitForSelector("text=Split the bill");
  await page.click("button[type=submit]:has-text('Fork it')");
  await sleep(300);
  await shot(page, "d18-validation", { clip: { x: 0, y: 300, width: 1920, height: 700 } });
  await ctx.close();
}

async function mobile(browser) {
  const ctx = await browser.newContext({
    viewport: { width: 390, height: 844 },
    deviceScaleFactor: 2,
    isMobile: true,
    hasTouch: true,
  });
  const page = await ctx.newPage();
  page.on("pageerror", (e) => errors.push(`[mobile] ${e.message}`));
  await page.goto(`${BASE}/?mock=1#/`);
  await page.waitForSelector("text=Split the bill");
  await sleep(600);
  await shot(page, "m01-home");
  await shot(page, "m01-home-full", { fullPage: true });

  await page.goto(`${BASE}/?mock=1#/run/sample-bill-split`);
  await page.waitForSelector("text=Recorded run");
  await sleep(1500);
  await shot(page, "m02-run-top");
  await page.locator("text=meanings").first().scrollIntoViewIfNeeded();
  await sleep(500);
  await shot(page, "m03-meanings");
  const groups = page.locator("[role=radiogroup]");
  await groups.nth(0).locator("label").first().click();
  await groups.nth(1).locator("label").first().click();
  await page.click("button:has-text('Lock it in')");
  await page.waitForSelector("text=Re-fork clarified spec", { timeout: 15000 });
  await sleep(1500);
  await page.click("button:has-text('Re-fork clarified spec')");
  await page.waitForSelector("text=Re-fork again", { timeout: 20000 });
  await sleep(1800);
  await page.locator("text=Agreement with your intent").scrollIntoViewIfNeeded();
  await sleep(300);
  await shot(page, "m04-converged");
  await shot(page, "m05-full", { fullPage: true });
  await ctx.close();
}

const browser = await chromium.launch({ executablePath: findChromium() });
try {
  const only = process.env.ONLY;
  if (!only || only === "desktop") await desktop(browser);
  if (!only || only === "mobile") await mobile(browser);
} finally {
  await browser.close();
}
if (errors.length) {
  console.log("\nConsole/page errors:");
  for (const e of errors) console.log(" ", e);
  process.exitCode = 1;
} else console.log("\nNo console errors.");
