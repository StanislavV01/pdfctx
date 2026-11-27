// Screenshots of the running demo for visual review (CI job "screens").
// Needs the API on NEXT_PUBLIC_PDFCTX_API and the UI on UI_URL.
import { mkdirSync } from "node:fs";
import { chromium } from "playwright";

const API = process.env.NEXT_PUBLIC_PDFCTX_API ?? "http://127.0.0.1:8000";
const UI = process.env.UI_URL ?? "http://localhost:3000";
const QUERY = process.env.DEMO_QUERY ?? "capital expenditure 2018";
const OUT = "screens";
mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 1 });
const errors = [];
page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
page.on("pageerror", (e) => errors.push(String(e)));

await page.goto(UI, { waitUntil: "networkidle" });
await page.screenshot({ path: `${OUT}/1-documents.png`, fullPage: true });

const { documents } = await (await fetch(`${API}/v1/documents`)).json();
const doc = documents.find((d) => d.status === "ok");
await page.goto(`${UI}/d/${encodeURIComponent(doc.id)}`, { waitUntil: "networkidle" });
await page.screenshot({ path: `${OUT}/2-viewer.png` });

await page.getByPlaceholder(/Ask the document/).fill(QUERY);
await page.getByRole("button", { name: "Search" }).click();
await page.getByText("context_pack").waitFor({ timeout: 30000 });
await page.waitForLoadState("networkidle");
await page.waitForTimeout(500);
await page.screenshot({ path: `${OUT}/3-search.png` });

await page.goto(`${UI}/audit`, { waitUntil: "networkidle" });
await page.screenshot({ path: `${OUT}/4-audit.png`, fullPage: true });

await browser.close();
console.log(`screens written; console errors: ${errors.length}`);
for (const e of errors) console.log(`  ${e}`);
if (errors.length) process.exitCode = 1;
