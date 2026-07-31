import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "../src/i18n/catalogs");
const en = JSON.parse(fs.readFileSync(path.join(root, "en.json"), "utf8"));
const zh = JSON.parse(fs.readFileSync(path.join(root, "zh-CN.json"), "utf8"));
const identicalAllowlist = new Set([
  "automations.ownerRepo",
  "connectors.github.github",
  "connectors.gmail.gmail",
  "connectors.hubspot.hubspot",
  "connectors.slack.help.emmaW",
  "connectors.slack.help.general",
  "connectors.slack.help.jiraVsLinear",
  "connectors.slack.help.launchRoom",
  "connectors.slack.help.priyaN",
  "connectors.slack.slack",
  "settings.macos12AppleSiliconM1",
  "settings.mb",
  "settings.openworker",
  "settings.rvmRemoteVirtualMachines",
  "settings.windows1022H211X64",
  "workspace.trust.pathProject",
]);
const enKeys = new Set(Object.keys(en));
const zhKeys = new Set(Object.keys(zh));
const missingInEn = [...zhKeys].filter((key) => !enKeys.has(key));
const missingInZh = [...enKeys].filter((key) => !zhKeys.has(key));
const source = path.resolve(here, "../src");
const text = collect(source);
const keys = new Set([
  ...text.matchAll(/\bt\("([^"]+)"/g),
  ...text.matchAll(/\blabelKey:\s*"([^"]+)"/g),
].map((match) => match[1]));
const missingEn = [...keys].filter((key) => !(key in en));
const missingZh = [...keys].filter((key) => !(key in zh));
const identical = [...keys].filter(
  (key) => key !== "test.englishFallback" && en[key] === zh[key] && !identicalAllowlist.has(key),
);
const invalid = Object.keys(en).filter(
  (key) => key !== "test.englishFallback" && (/^ui\./.test(key) || /(?:^|\.)([0-9a-f]{8,})$/.test(key)),
);
const unused = Object.keys(en).filter((key) => !keys.has(key) && !key.startsWith("test."));
const entities = [...Object.entries(en), ...Object.entries(zh)]
  .filter(([, value]) => /&(?:amp|apos|quot|lt|gt|rsquo|lsquo);/i.test(value))
  .map(([key, value]) => ({ key, value }));
// High-confidence guardrails for the most commonly missed UI copy. Comments are removed before
// scanning so prose in source comments does not count as rendered text. A broader JSX-literal
// rule would flag technical labels and examples throughout the app; catalog usage plus this
// focused list keeps the check actionable.
const requiredLiteralChecks = [
  "Theme",
  "Language",
  "Sidebar",
  "Browse",
  "Run setup again",
  "Check for updates",
  "Ask the coworker",
  "Ask for approval",
  "Start a new shell",
];
const renderedSource = text
  .replace(/\/\*[\s\S]*?\*\//g, "")
  .replace(/^\s*\/\/.*$/gm, "");
const literalUi = requiredLiteralChecks.filter((literal) => {
  const escaped = literal.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return new RegExp(`(?:>|["'])\\s*${escaped}\\s*(?:<|["'])`).test(renderedSource);
});
if (
  missingInEn.length ||
  missingInZh.length ||
  missingEn.length ||
  missingZh.length ||
  invalid.length ||
  identical.length ||
  unused.length ||
  entities.length ||
  literalUi.length
) {
  console.error(JSON.stringify({
    missingInEn,
    missingInZh,
    missingEn,
    missingZh,
    invalid,
    identical,
    unused,
    entities,
    literalUi,
  }, null, 2));
  process.exit(1);
}
console.log(`${keys.size} source translation keys checked (${enKeys.size} catalog entries)`);

function collect(dir) {
  return fs.readdirSync(dir, { withFileTypes: true }).map((entry) => {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) return collect(full);
    return /\.(tsx?|jsx?)$/.test(entry.name) && !entry.name.endsWith(".test.tsx")
      ? fs.readFileSync(full, "utf8")
      : "";
  }).join("\n");
}
