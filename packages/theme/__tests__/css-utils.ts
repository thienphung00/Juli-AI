/**
 * Tiny flat-CSS parsing + token-resolution helpers shared by the
 * run-surface test files (#1912 / ADR-102). Both stylesheets under test
 * are flat (no nesting beyond one `@media` wrapper, whose inner rules the
 * block regex still captures individually with their own selectors --
 * the dangling `@media` header never forms a block of its own because
 * `[^{}]+` cannot cross a `{`).
 */

export function stripCssComments(css: string): string {
  return css.replace(/\/\*[\s\S]*?\*\//g, "");
}

export interface RuleBlock {
  selector: string;
  body: string;
}

export function extractRuleBlocks(css: string): RuleBlock[] {
  const blocks: RuleBlock[] = [];
  const withoutComments = stripCssComments(css);
  const re = /([^{}]+)\{([^{}]*)\}/g;
  let match: RegExpExecArray | null;
  while ((match = re.exec(withoutComments)) !== null) {
    const selector = match[1].trim();
    if (!selector) continue; // stray braces left by a stripped comment
    blocks.push({ selector, body: match[2] });
  }
  return blocks;
}

export function extractDeclarations(body: string): Record<string, string> {
  const declarations: Record<string, string> = {};
  for (const rawDecl of body.split(";")) {
    const decl = rawDecl.trim();
    if (!decl) continue;
    const colonIndex = decl.indexOf(":");
    if (colonIndex === -1) continue;
    const property = decl.slice(0, colonIndex).trim();
    const value = decl.slice(colonIndex + 1).trim();
    declarations[property] = value;
  }
  return declarations;
}

const VAR_REFERENCE_RE = /^var\((--[a-z0-9-]+)(?:\s*,\s*[^()]*)?\)$/i;

/**
 * Resolves a token value that may be a `var(--x)` chain (with or without
 * a fallback) through the scoped map first, then the app-wide map --
 * deep enough for the run-surface file, which chains at most
 * focus-ring -> live-edge -> app-wide primary-text -> hex.
 */
export function resolveTokenValue(
  name: string,
  scoped: Record<string, string>,
  appWide: Record<string, string>,
  maxDepth = 5,
): string {
  let current = scoped[name] ?? appWide[name];
  if (current === undefined) {
    throw new Error(`css-utils: token ${name} is not declared in either token map`);
  }
  for (let depth = 0; depth < maxDepth; depth += 1) {
    const varMatch = VAR_REFERENCE_RE.exec(current.trim());
    if (!varMatch) return current.trim();
    const next = scoped[varMatch[1]] ?? appWide[varMatch[1]];
    if (next === undefined) {
      throw new Error(`css-utils: ${name} references unknown token ${varMatch[1]}`);
    }
    current = next;
  }
  throw new Error(`css-utils: ${name} exceeds var() resolution depth ${maxDepth}`);
}
