// QA: un still por golpe (o los frames que se pasen como argumentos).
//   node scripts/stills.mjs            → golpes 0..59
//   node scripts/stills.mjs 300 467    → esos frames
// Chromium: REMOTION_BROWSER o el headless de Playwright si existe.
import { bundle } from "@remotion/bundler";
import { renderStill, selectComposition } from "@remotion/renderer";
import { existsSync, mkdirSync } from "node:fs";
import path from "node:path";
import { webpackOverride } from "../webpack-override.mjs";

const root = path.resolve(import.meta.dirname, "..");
const browser =
  process.env.REMOTION_BROWSER ??
  ["/opt/pw-browsers/chromium_headless_shell-1194/chrome-linux/headless_shell"].find((p) => existsSync(p));
const out = path.join(root, "out", "stills");
mkdirSync(out, { recursive: true });

const frames = process.argv.slice(2).length
  ? process.argv.slice(2).map(Number)
  : Array.from({ length: 60 }, (_, n) => Math.min(1799, 17 + 30 * n));

const serveUrl = await bundle({ entryPoint: path.join(root, "src", "index.ts"), webpackOverride });
const composition = await selectComposition({ serveUrl, id: "EchoDemo", browserExecutable: browser });
for (const frame of frames) {
  const output = path.join(out, `f${String(frame).padStart(4, "0")}.png`);
  await renderStill({ composition, serveUrl, frame, output, browserExecutable: browser, imageFormat: "png" });
  console.log(output);
}
