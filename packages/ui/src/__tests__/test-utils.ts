import { readFileSync } from "node:fs";
import { join } from "node:path";

export function loadUiStyles(): string {
  return readFileSync(join(process.cwd(), "styles.css"), "utf8");
}

export function loadUiStyleRules(): string {
  return loadUiStyles().replace(/\/\*[\s\S]*?\*\//g, "");
}
