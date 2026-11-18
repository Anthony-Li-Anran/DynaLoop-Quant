// Wraps display strings inside array literals that are consumed by .map() as
// table headers / options labels. This is the only safe "data position" rule.
import fs from "node:fs";
import path from "node:path";

const files = process.argv.slice(2);
const esc = (s) => s.replace(/\\/g, "\\\\").replace(/"/g, '\\"');
const UI_WORDS = new Set([
  "Buy", "Sell", "Preview", "Replay", "Cancel", "Close", "Remove", "Edit",
  "Archive", "Restore", "Pending", "Abstained", "Yes", "No", "None",
  "Decision", "Formula", "Coverage", "Period", "Status", "Type", "Name",
  "Value", "Source", "Version", "Runs", "Folds", "Rounds", "Evidence",
]);
function isCopy(v) {
  if (v.length < 2 || v.length > 120 || !/[A-Za-z]/.test(v)) return false;
  if (/[=<>{}`\\;]/.test(v)) return false;
  if (/^https?:|^\/|^[a-z][A-Za-z0-9]*$/.test(v)) return false;
  const words = v.trim().split(/[\s/·\-–]+/).filter(Boolean);
  return words.length >= 2 || UI_WORDS.has(v.trim());
}
function wrap(src) {
  // A) array literal of strings immediately consumed by .map
  src = src.replace(/\[((?:"[^"\\]{2,120}",\s*)*"[^"\\]{2,120}")\]\s*\.map/g, (m, inner) => {
    const wrapped = inner.replace(/"([^"\\]{2,120})"/g, (mm, v) => (isCopy(v) ? `t("${esc(v)}")` : mm));
    return `[${wrapped}].map`;
  });
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
