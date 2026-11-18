// Fourth pass: wrap remaining literal-string display attributes and defaults:
//   description="X"  aria-label="X"  (not already {t(...)})
//   param = "X"  in function signatures (emptyTitle = "...", title = "...")
//   label:"X"  inside options arrays
// Conservative prose check; skips already-wrapped and code-like strings.
import fs from "node:fs";
import path from "node:path";

const files = process.argv.slice(2);
const esc = (s) => s.replace(/\\/g, "\\\\").replace(/"/g, '\\"');
const UI_WORDS = new Set([
  "Buy", "Sell", "Preview", "Replay", "Cancel", "Close", "Remove", "Edit",
  "Archive", "Restore", "Pending", "Abstained", "Yes", "No", "None", "Done",
]);
function isCopy(v) {
  if (v.length < 3 || v.length > 160 || !/[A-Za-z]/.test(v)) return false;
  if (/[=<>{}`\\;]/.test(v)) return false;
  if (/^https?:|^\/|^[a-z][A-Za-z0-9]*$/.test(v)) return false;
  if (/^[A-Z][A-Z0-9_]*$/.test(v)) return false;
  const words = v.trim().split(/[\s/·\-–]+/).filter(Boolean);
  return words.length >= 2 || UI_WORDS.has(v.trim());
}
function wrap(src) {
  // description="X" / aria-label="X" / placeholder="X" (string literal form)
  src = src.replace(/\b(description|aria-label|placeholder|emptyDescription|emptyTitle)="([^"\\]{3,160})"/g,
    (m, attr, v) => (isCopy(v) ? `${attr}={t("${esc(v)}")}` : m));
  // options arrays label:"X"
  src = src.replace(/\b(label)\s*:\s*"([^"\\]{3,160})"/g,
    (m, key, v) => (isCopy(v) ? `${key}: t("${esc(v)}")` : m));
  return src;
}
let total = 0;
for (const file of files) {
  const abs = path.resolve(file);
  let src = fs.readFileSync(abs, "utf8");
  const before = src;
  src = wrap(src);
  if (src !== before) {
    fs.writeFileSync(abs, src, "utf8");
    const n = (src.match(/\bt\("/g) || []).length - (before.match(/\bt\("/g) || []).length;
    total += n;
    console.log(`+${n}  ${file}`);
  }
}
console.log(`TOTAL: ${total}`);
