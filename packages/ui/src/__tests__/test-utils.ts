import { readFileSync } from "node:fs";
import { join } from "node:path";

export function loadUiStyles(): string {
  const raw = readFileSync(join(process.cwd(), "styles.css"), "utf8");
  return raw.replace(/\/\*[\s\S]*?\*\//g, "");
}

export function loadUiStyleRules(): string {
  return loadUiStyles().replace(/\/\*[\s\S]*?\*\//g, "");
}
