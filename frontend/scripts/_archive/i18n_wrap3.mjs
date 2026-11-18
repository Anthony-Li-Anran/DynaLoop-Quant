// Third pass: wrap strings in data-ish positions that are actually display copy:
//   - string array literals: ["Decision", "Submitted (UTC)", ...].map(...)
//   - nullish/ternary fallbacks: ?? "Equal weight"  /  : "Pending"
//   - object display fields: label: "..." / name: "..." / text: "..."
// Only wraps prose-looking strings (>=2 words) or an allow-list of UI words.
import fs from "node:fs";
import path from "node:path";

const files = process.argv.slice(2);
const esc = (s) => s.replace(/\\/g, "\\\\").replace(/"/g, '\\"');
const UI_WORDS = new Set([
  "Buy", "Sell", "Preview", "Replay", "Cancel", "Close", "Remove", "Edit",
  "Archive", "Restore", "Pending", "Abstained", "Yes", "No", "None",
  "Overview", "Loading", "Data", "Settings", "Runtime", "Evidence",
]);

function isCopy(v) {
  if (v.length < 2 || v.length > 120) return false;
  if (!/[A-Za-z]/.test(v)) return false;
  if (/[=<>{}`\\;]/.test(v)) return false;
  if (v.includes("=>")) return false;
  if (/^https?:|^\/|^[a-z][A-Za-z0-9]*$/.test(v)) return false;
  const words = v.trim().split(/[\s/·\-–]+/).filter(Boolean);
  if (words.length >= 2) return true;
  return UI_WORDS.has(v.trim());
}

function wrap(src) {
  // A) array literal of strings followed by .map -> column/header labels
  src = src.replace(/\[((?:"[^"\\]{2,120}",\s*)*"[^"\\]{2,120}")\]\s*\.map/g, (m, inner) => {
    const wrapped = inner.replace(/"([^"\\]{2,120})"/g, (mm, v) => (isCopy(v) ? `t("${esc(v)}")` : mm));
    return `[${wrapped}].map`;
  });
  // B) fallbacks: ?? "X"  or  : "X"  (ternary else / default)
  src = src.replace(/(\?\?\s*|:\s*)"([^"\\]{2,120})"/g, (m, op, v) =>
    isCopy(v) ? `${op}t("${esc(v)}")` : m);
  // C) object display fields
  src = src.replace(/\b(label|name|text|title|value):\s*"([^"\\]{2,120})"/g, (m, key, v) =>
    isCopy(v) ? `${key}: t("${esc(v)}")` : m);
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
