import { chromium } from "playwright";
const errors = [];
const browser = await chromium.launch();
async function run(name, viewport, theme) {
  const ctx = await browser.newContext({ viewport, colorScheme: theme });
  const page = await ctx.newPage();
  page.on("console", (m) => m.type() === "error" && errors.push(`[${name}] console: ${m.text()}`));
  page.on("pageerror", (e) => errors.push(`[${name}] pageerror: ${e.message}`));
  page.on("response", (r) => r.status() >= 400 && errors.push(`[${name}] HTTP ${r.status()} ${r.url()}`));
  const shot = (n) => page.screenshot({ path: `../shots/${name}-${n}.png`, fullPage: true });
  await page.goto("http://localhost:8000/");
  await page.getByText("Try a sample scenario").waitFor();
  await shot("overview");
  // run a scenario from the overview
  await page.getByRole("button", { name: "Run analysis" }).first().click();
  await page.waitForURL(/\/analyses\//);
  await page.getByText("Recommended actions").waitFor();
  await shot("result-findings");
  for (const tab of ["Schema", "Data & metrics", "Impact graph", "SQL & limits"]) {
    await page.getByRole("tab", { name: new RegExp(tab.replace("&", "&")) }).click();
    await page.waitForTimeout(tab === "Impact graph" ? 1200 : 200);
    await shot("result-" + tab.split(" ")[0].toLowerCase());
  }
  // downloads
  const [dl] = await Promise.all([page.waitForEvent("download"), page.getByRole("button", { name: "HTML" }).click()]);
  console.log(name, "download:", dl.suggestedFilename());
  // analyze page: custom SQL
  await page.goto("http://localhost:8000/analyze");
  await page.locator(".cm-content").waitFor();
  await page.locator(".cm-content").click();
  await page.keyboard.press("Control+A");
  await page.keyboard.type("ALTER TABLE orders DROP COLUMN discount_code;");
  await shot("analyze");
  await page.getByRole("button", { name: "Analyze change" }).click();
  await page.waitForURL(/\/analyses\//);
  await page.getByText("Recommended actions").or(page.getByText("Findings (")).first().waitFor();
  console.log(name, "custom result title:", await page.locator("h2").first().innerText());
  await shot("custom-result");
  // connections + schema
  await page.goto("http://localhost:8000/connections");
  await page.getByText("orders").first().waitFor();
  await page.getByRole("button", { name: /^orders/ }).click();
  await shot("connections");
  // baselines
  await page.goto("http://localhost:8000/baselines");
  await page.getByRole("button", { name: "Capture baseline" }).click();
  await page.getByRole("button", { name: "Compare" }).first().waitFor();
  await page.getByRole("button", { name: "Compare" }).first().click();
  await page.getByText(/schema signature is/).first().waitFor({ timeout: 60000 });
  await shot("baselines");
  await page.goto("http://localhost:8000/history");
  await page.getByText("Loading…").waitFor({ state: "detached" });
  await shot("history");
  await page.getByLabel("Search analyses").fill("zzz-no-such-title");
  await page.getByText("No analyses match these filters.").waitFor();
  if (process.env.E2E_CONNECT) await connectFlow(page, shot);
  await ctx.close();
}

// Needs a self-hosted server with the `sample` extra: start the sample database, test, save, browse, preview, analyze.
async function connectFlow(page, shot) {
  await page.goto("http://localhost:8000/connections");
  await page.getByRole("radio", { name: /PostgreSQL/ }).click();
  await page.getByRole("button", { name: "Launch sample database" }).click();
  await page.getByText("Connection works").waitFor({ timeout: 120000 });
  await shot("connect-tested");
  await page.getByRole("button", { name: "Save connection" }).click();
  await page.getByText("is connected").waitFor();
  await page.getByRole("button", { name: /^orders/ }).first().click();
  await page.getByRole("button", { name: "Preview rows" }).click();
  await page.getByText(/First \d+ rows/).waitFor();
  await shot("connect-browse");
  await page.goto("http://localhost:8000/analyze");
  await page.getByRole("button", { name: /Drop / }).first().click();
  await page.keyboard.press("Control+Enter");
  await page.getByText("Recommended actions").or(page.getByText("Findings (")).first().waitFor({ timeout: 120000 });
  await shot("connect-analysis");
}
await run("desktop-light", { width: 1280, height: 900 }, "light");
await run("mobile-dark", { width: 390, height: 844 }, "dark");
await browser.close();
console.log(errors.length ? "ERRORS:\n" + errors.join("\n") : "no console/network errors");
