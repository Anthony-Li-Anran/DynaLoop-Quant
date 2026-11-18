// Conservative codemod: wraps user-visible static English strings in t(...).
// Two safe transformations only:
//   1) display props with plain string literal values (allow-list)
//   2) JSX text nodes that are pure prose (no code punctuation, not after '=>')
// Never touches className, enum values, data keys, imports, or interpolations.
import fs from "node:fs";
import path from "node:path";

const files = process.argv.slice(2);

const DISPLAY_PROPS = [
  "title", "description", "label", "eyebrow", "note", "placeholder",
  "emptyTitle", "emptyDescription", "emptyMessage", "heading", "subtitle",
  "caption", "tooltip", "hint", "text", "message",
];

const COMMON_LOWER = new Set([
  "overview", "data", "settings", "runtime", "evidence", "experiments",
  "backtests", "decision", "subjective", "research", "loop", "components",
]);

function isCopy(s) {
  const t = s.trim();
  if (!t || t.length < 2 || t.length > 160) return false;
  if (!/[A-Za-z]/.test(t)) return false;
  if (/^[a-z][A-Za-z0-9_]*$/.test(t) && !COMMON_LOWER.has(t)) return false;
  if (/^(https?:|\/|\.|#|rgb|rgba)/.test(t)) return false;
  // Reject anything that looks like code / identifiers / CSS.
  if (/[=;(){}\[\]`\\|<>]/.test(t)) return false;
  if (/^[A-Z][A-Z0-9_]*$/.test(t)) return false; // SCREAMING_CASE constant
  if (/^[a-z]+[A-Z]/.test(t) && !t.includes(" ")) return false; // camelCase single token
  return true;
}

const esc = (s) => s.replace(/\\/g, "\\\\").replace(/"/g, '\\"').replace(/\n/g, "\\n");

function wrapDisplayProps(src) {
  return src.replace(
    new RegExp(`\\b(${DISPLAY_PROPS.join("|")})="([^"{}]*)"`, "g"),
    (m, prop, value) => (isCopy(value) ? `${prop}={t("${esc(value)}")}` : m),
  );
}

function wrapJsxText(src) {
  // '>' not preceded by '=' or '>' (excludes => and ->), then pure prose, then '<'.
  return src.replace(
    /(?<![=>])>(\s*)([A-Za-z][^<>]{1,160}?)(\s*)</g,
    (m, lead, rawText, trail) => {
      const text = rawText.trim();
      if (!isCopy(text)) return m;
      // Exclude TypeScript generic closes like Foo<Bar>[]
      if (/^(string|number|boolean|any|void|Record|Array|Column|React|JSX)$/.test(text)) return m;
      return `>${lead}{t("${esc(text)}")}${trail}<`;
    },
  );
}

let total = 0;
for (const file of files) {
  const abs = path.resolve(file);
  let src = fs.readFileSync(abs, "utf8");
  const before = src;
  src = wrapDisplayProps(src);
  src = wrapJsxText(src);
  if (src !== before) {
    fs.writeFileSync(abs, src, "utf8");
    const n = (src.match(/\bt\("/g) || []).length - (before.match(/\bt\("/g) || []).length;
    total += n;
    console.log(`wrapped ${String(n).padStart(3)}  ${file}`);
  }
}
console.log(`TOTAL: ${total}`);
