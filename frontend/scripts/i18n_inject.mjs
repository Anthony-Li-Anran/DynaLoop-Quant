// Injects useTranslation import + hook into files already wrapped by i18n_wrap.mjs.
// Strategy: locate each `function Name(...) {` body start via signature paren match.
// A function "uses t" if the source between its body start and the NEXT function's
// body start (or EOF) contains t("..."). This avoids fragile JSX brace matching.
import fs from "node:fs";
import path from "node:path";

const files = process.argv.slice(2);

function locateFunctions(src) {
  const re = /\bfunction\s+[A-Z][A-Za-z0-9_]*\s*[<(]/g;
  const starts = [];
  let m;
  while ((m = re.exec(src))) starts.push(m.index);
  const result = [];
  for (const start of starts) {
    let open = -1;
    for (let i = start; i < src.length; i++) if (src[i] === "(") { open = i; break; }
    if (open < 0) continue;
    let paren = 0, close = -1;
    for (let i = open; i < src.length; i++) {
      if (src[i] === "(") paren++;
      else if (src[i] === ")") { paren--; if (paren === 0) { close = i; break; } }
    }
    if (close < 0) continue;
    let bodyStart = -1;
    for (let i = close + 1; i < src.length; i++) {
      if (src[i] === "{") { bodyStart = i; break; }
      if (src[i] === ";") break;
    }
    if (bodyStart >= 0) result.push(bodyStart);
  }
  return result.sort((a, b) => a - b);
}

let totalHooks = 0;
for (const file of files) {
  const abs = path.resolve(file);
  let src = fs.readFileSync(abs, "utf8");
  const before = src;
  if (!src.includes('t("') && !src.includes("t(`")) continue;

  const bodyStarts = locateFunctions(src);
  const edits = [];
  for (let k = 0; k < bodyStarts.length; k++) {
    const bs = bodyStarts[k];
    const next = k + 1 < bodyStarts.length ? bodyStarts[k + 1] : src.length;
    const region = src.slice(bs, next);
    if (!region.includes('t("') && !region.includes("t(`")) continue;
    const head = src.slice(bs, bs + 200);
    if (/const\s*\{\s*t\s*\}\s*=\s*useTranslation/.test(head)) continue;
    const lineMatch = src.slice(bs + 1).match(/\n(\s*)\S/);
    const indent = lineMatch ? lineMatch[1] : "  ";
    edits.push({ pos: bs + 1, text: `\n${indent}const { t } = useTranslation();` });
  }
  for (const e of edits.sort((a, b) => b.pos - a.pos)) {
    src = src.slice(0, e.pos) + e.text + src.slice(e.pos);
  }
  totalHooks += edits.length;

  if (src.includes("useTranslation()") && !src.includes("react-i18next")) {
    const importLines = [...src.matchAll(/^import .*?;$/gm)];
    const last = importLines[importLines.length - 1];
    const insertPos = last ? last.index + last[0].length : 0;
    src = src.slice(0, insertPos) + '\nimport { useTranslation } from "react-i18next";' + src.slice(insertPos);
  }

  if (src !== before) {
    fs.writeFileSync(abs, src, "utf8");
    console.log(`hooks ${String(edits.length).padStart(2)}  ${file}`);
  } else {
    console.log(`no change  ${file}`);
  }
}
console.log(`TOTAL hooks injected: ${totalHooks}`);
