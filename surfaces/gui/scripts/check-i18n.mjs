import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "../src/i18n/catalogs");
const en = JSON.parse(fs.readFileSync(path.join(root, "en.json"), "utf8"));
const zh = JSON.parse(fs.readFileSync(path.join(root, "zh-CN.json"), "utf8"));
const source = path.resolve(here, "../src");
const text = collect(source);
const keys = new Set([...text.matchAll(/\bt\("([^"]+)"/g)].map((match) => match[1]));
const missingEn = [...keys].filter((key) => !(key in en));
const invalid = Object.keys(en).filter(
  (key) => key !== "test.englishFallback" && (/^ui\./.test(key) || /(?:^|\.)([0-9a-f]{8,})$/.test(key)),
);
const unused = Object.keys(en).filter((key) => !keys.has(key) && !key.startsWith("test."));
if (missingEn.length || invalid.length || unused.length) {
  console.error(JSON.stringify({ missingEn, invalid, unused }, null, 2));
  process.exit(1);
}
console.log(`${keys.size} translation keys checked`);

function collect(dir) {
  return fs.readdirSync(dir, { withFileTypes: true }).map((entry) => {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) return collect(full);
    return /\.(tsx?|jsx?)$/.test(entry.name) && !entry.name.endsWith(".test.tsx")
      ? fs.readFileSync(full, "utf8")
      : "";
  }).join("\n");
}
