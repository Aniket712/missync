import { chromium } from "playwright";
import { pathToFileURL } from "url";
import path from "path";
const src = path.resolve("../docs/handbook/handbook.html");
const out = path.resolve(process.argv[2] ?? "../docs/Missync-Handbook.pdf");
const b = await chromium.launch();
const p = await b.newPage();
await p.goto(pathToFileURL(src).href, { waitUntil: "load" });
await p.pdf({
  path: out, format: "A4", printBackground: true, displayHeaderFooter: true,
  margin: { top: "18mm", bottom: "18mm", left: "16mm", right: "16mm" },
  headerTemplate: "<div></div>",
  footerTemplate: `<div style="width:100%;font-size:8px;color:#5b6575;padding:0 16mm;display:flex;justify-content:space-between;font-family:Segoe UI,Arial"><span>Missync Handbook — Catch data changes before they break what depends on them.</span><span><span class="pageNumber"></span> / <span class="totalPages"></span></span></div>`,
});
await b.close();
console.log("ok");
