// Second pass: wrap remaining JSX text nodes and th/label/button text that the
// conservative first pass skipped (parentheses, slashes, symbols). Still avoids
// code punctuation and never double-wraps existing t(...) calls.
import fs from "node:fs";
import path from "node:path";

const files = process.argv.slice(2);
const esc = (s) => s.replace(/\\/g, "\\\\").replace(/"/g, '\\"');

function ok(text) {
  const t = text.trim();
  if (!t || t.length < 2 || t.length > 140) return false;
  if (!/[A-Za-z]/.test(t)) return false;
  // code punctuation that means this is not prose
  if (/[={};`\\]/.test(t)) return false;
  if (t.includes("=>") || t.includes("->")) return false;
  if (/^[A-Z][A-Z0-9_]*$/.test(t)) return false;
  // allow prose symbols: () / · × Δ − ¥ % . , & ' + - :
  if (/[<>]/.test(t)) return false;
  return true;
}

function wrapTextNodes(src) {
  // >text< where text has no angle brackets/expressions; allow broad prose symbols.
  return src.replace(/(?<![=>])>(\s*)([^<>]{1,140}?)(\s*)</g, (m, lead, raw, trail) => {
    const text = raw.trim();
    if (!ok(text)) return m;
    // skip if this region is part of a JS comparison/generic (heuristic: starts with operator chars)
    if (/^[\])}?:;,]/.test(text)) return m;
    return `>${lead}{t("${esc(text)}")}${trail}<`;
  });
}

let total = 0;
for (const file of files) {
  const abs = path.resolve(file);
  let src = fs.readFileSync(abs, "utf8");
  const before = src;
  src = wrapTextNodes(src);
  if (src !== before) {
    fs.writeFileSync(abs, src, "utf8");
    const n = (src.match(/\bt\("/g) || []).length - (before.match(/\bt\("/g) || []).length;
    total += n;
    console.log(`+${n}  ${file}`);
  }
}
console.log(`TOTAL: ${total}`);
