import Link from "next/link";
import type { ReactNode } from "react";

import { BLOG_FIGURES } from "../../content/blog/figures";
import { BlogFigureView } from "./figure";

/**
 * A deliberately small Markdown subset for blog bodies, parsed and rendered on
 * the server (no client JS, no dependency). Supported:
 *
 *   ## Heading 2            ### Heading 3          (ids from the text, TOC from H2)
 *   paragraph text          blank line between blocks
 *   - bullet                1. numbered
 *   > callout line          (consecutive lines join into one callout)
 *   | a | b |               table: header row, `|---|---|` row, body rows
 *   **bold**   [text](/internal-or-https-url)
 *   {{hinh:gmv-pheu}}       figure on a line of its own (id from content/blog/figures.ts)
 *
 * Anything else is plain text. No raw HTML.
 */

export type Block =
  | { kind: "h2" | "h3"; text: string; id: string }
  | { kind: "p"; text: string }
  | { kind: "ul" | "ol"; items: string[] }
  | { kind: "callout"; lines: string[] }
  | { kind: "table"; header: string[]; rows: string[][] }
  | { kind: "figure"; id: string };

/** `{{hinh:<id>}}` on a line of its own: an inline figure (D48 additions 7). */
const FIGURE_LINE = /^\{\{hinh:([a-z0-9-]+)\}\}$/;

export interface TocEntry {
  id: string;
  text: string;
}

/** `Tỷ lệ nhấp (CTR) là gì?` → `ty-le-nhap-ctr-la-gi`. */
export function slugify(text: string): string {
  return text
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/đ/g, "d")
    .replace(/Đ/g, "D")
    .toLowerCase()
    .replace(/\*\*|\[|\]\([^)]*\)/g, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

function splitRow(line: string): string[] {
  return line
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((cell) => cell.trim());
}

export function parseMarkdown(source: string): Block[] {
  const blocks: Block[] = [];
  const usedIds = new Map<string, number>();
  const lines = source.replace(/\r\n/g, "\n").split("\n");
  let i = 0;

  const uniqueId = (text: string) => {
    const base = slugify(text) || "muc";
    const seen = usedIds.get(base) ?? 0;
    usedIds.set(base, seen + 1);
    return seen === 0 ? base : `${base}-${seen + 1}`;
  };

  while (i < lines.length) {
    const line = lines[i]!;
    const trimmed = line.trim();
    if (trimmed === "") {
      i += 1;
      continue;
    }
    const heading = /^(#{2,3})\s+(.+)$/.exec(trimmed);
    if (heading) {
      const text = heading[2]!.trim();
      blocks.push({ kind: heading[1] === "##" ? "h2" : "h3", text, id: uniqueId(text) });
      i += 1;
      continue;
    }
    const figure = FIGURE_LINE.exec(trimmed);
    if (figure) {
      blocks.push({ kind: "figure", id: figure[1]! });
      i += 1;
      continue;
    }
    if (trimmed.startsWith("{{")) {
      throw new Error(`Blog markdown: a figure line is {{hinh:<id>}} ("${trimmed.slice(0, 40)}")`);
    }
    if (/^#\s/.test(trimmed) || /^#{4,}\s/.test(trimmed)) {
      throw new Error(`Blog markdown: only ## and ### headings are allowed ("${trimmed.slice(0, 40)}")`);
    }
    if (trimmed.startsWith("|")) {
      const rows: string[] = [];
      while (i < lines.length && lines[i]!.trim().startsWith("|")) {
        rows.push(lines[i]!.trim());
        i += 1;
      }
      if (rows.length < 2 || !/^\|[\s:|-]+\|?$/.test(rows[1]!)) {
        throw new Error(`Blog markdown: a table needs a header and a |---| row ("${rows[0]}")`);
      }
      blocks.push({ kind: "table", header: splitRow(rows[0]!), rows: rows.slice(2).map(splitRow) });
      continue;
    }
    if (/^[-*]\s+/.test(trimmed) || /^\d+\.\s+/.test(trimmed)) {
      const ordered = /^\d+\.\s+/.test(trimmed);
      const pattern = ordered ? /^\d+\.\s+/ : /^[-*]\s+/;
      const items: string[] = [];
      while (i < lines.length && pattern.test(lines[i]!.trim())) {
        items.push(lines[i]!.trim().replace(pattern, ""));
        i += 1;
      }
      blocks.push({ kind: ordered ? "ol" : "ul", items });
      continue;
    }
    if (trimmed.startsWith(">")) {
      const calloutLines: string[] = [];
      while (i < lines.length && lines[i]!.trim().startsWith(">")) {
        calloutLines.push(lines[i]!.trim().replace(/^>\s?/, ""));
        i += 1;
      }
      blocks.push({ kind: "callout", lines: calloutLines.filter((l) => l !== "") });
      continue;
    }
    const paragraph: string[] = [];
    while (i < lines.length) {
      const next = lines[i]!.trim();
      if (next === "" || /^(#{1,6}\s|\||>|[-*]\s|\d+\.\s|\{\{)/.test(next)) break;
      paragraph.push(next);
      i += 1;
    }
    blocks.push({ kind: "p", text: paragraph.join(" ") });
  }
  return blocks;
}

export function tableOfContents(blocks: readonly Block[]): TocEntry[] {
  return blocks.flatMap((block) => (block.kind === "h2" ? [{ id: block.id, text: block.text }] : []));
}

/** Every `[text](href)` target in a body, in order. */
export function markdownLinks(source: string): string[] {
  return [...source.matchAll(/\[[^\]]+\]\(([^)\s]+)\)/g)].map((match) => match[1]!);
}

/** Visible words (space-separated tokens) after stripping Markdown syntax. */
export function countWords(source: string): number {
  const text = source
    .replace(/^\s*\{\{hinh:[^}]*\}\}\s*$/gm, "")
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/\*\*/g, "")
    .replace(/^#{2,3}\s+/gm, "")
    .replace(/^\s*(?:[-*]|\d+\.|>)\s+/gm, "")
    .replace(/^\|[\s:|-]+\|?$/gm, "")
    .replace(/\|/g, " ");
  return text.split(/\s+/).filter((token) => /[\p{L}\p{N}]/u.test(token)).length;
}

/** Minutes at ~220 words a minute, at least 1. */
export function readingMinutes(words: number): number {
  return Math.max(1, Math.round(words / 220));
}

const INLINE = /(\*\*[^*]+\*\*|\[[^\]]+\]\([^)\s]+\))/g;

/** Decides whether an internal link renders as a link (false → its label as plain text). */
export type LinkFilter = (href: string) => boolean;

const ALWAYS: LinkFilter = () => true;

export function renderInline(text: string, keyPrefix = "i", isLinkable: LinkFilter = ALWAYS): ReactNode[] {
  return text.split(INLINE).flatMap((part, index): ReactNode[] => {
    if (part === "") return [];
    const key = `${keyPrefix}-${index}`;
    if (part.startsWith("**") && part.endsWith("**")) {
      return [<strong key={key}>{renderInline(part.slice(2, -2), key, isLinkable)}</strong>];
    }
    const link = /^\[([^\]]+)\]\(([^)\s]+)\)$/.exec(part);
    if (link) {
      const [, label, href] = link as unknown as [string, string, string];
      if (!isLinkable(href)) return renderInline(label, key, isLinkable);
      if (href.startsWith("/") || href.startsWith("#")) {
        return [
          <Link className="lp-blog__link" href={href} key={key}>
            {renderInline(label, key, isLinkable)}
          </Link>,
        ];
      }
      return [
        <a className="lp-blog__link" href={href} key={key} rel="noopener noreferrer">
          {renderInline(label, key, isLinkable)}
        </a>,
      ];
    }
    return [part];
  });
}

export function MarkdownBlocks({
  blocks,
  isLinkable = ALWAYS,
}: {
  blocks: readonly Block[];
  /** A published post passes a filter that unlinks drafts (never link a noindex page). */
  isLinkable?: LinkFilter;
}) {
  const inline = (text: string, key: string) => renderInline(text, key, isLinkable);
  return (
    <>
      {blocks.map((block, index) => {
        const key = `b${index}`;
        switch (block.kind) {
          case "figure": {
            const figure = BLOG_FIGURES[block.id];
            if (!figure) throw new Error(`Blog markdown: unknown figure "${block.id}" (content/blog/figures.ts)`);
            return <BlogFigureView figure={figure} key={key} />;
          }
          case "h2":
            return (
              <h2 className="lp-blog__h2" id={block.id} key={key}>
                {block.text}
              </h2>
            );
          case "h3":
            return (
              <h3 className="lp-blog__h3" id={block.id} key={key}>
                {block.text}
              </h3>
            );
          case "p":
            return <p key={key}>{inline(block.text, key)}</p>;
          case "ul":
          case "ol": {
            const items = block.items.map((item, j) => (
              <li key={`${key}-${j}`}>{inline(item, `${key}-${j}`)}</li>
            ));
            return block.kind === "ul" ? <ul key={key}>{items}</ul> : <ol key={key}>{items}</ol>;
          }
          case "callout":
            return (
              <aside className="lp-blog__callout" key={key}>
                {block.lines.map((line, j) => (
                  <p key={`${key}-${j}`}>{inline(line, `${key}-${j}`)}</p>
                ))}
              </aside>
            );
          case "table":
            return (
              // Scrolls sideways on phones: a focusable, uniquely named region so keyboard users can scroll it.
              <div
                aria-label={`Bảng ${blocks.slice(0, index).filter((b) => b.kind === "table").length + 1}`}
                className="lp-blog__table-wrap"
                key={key}
                role="region"
                tabIndex={0}
              >
                <table className="lp-blog__table">
                  <thead>
                    <tr>
                      {block.header.map((cell, j) => (
                        <th key={`${key}-h${j}`} scope="col">
                          {inline(cell, `${key}-h${j}`)}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {block.rows.map((row, r) => (
                      <tr key={`${key}-r${r}`}>
                        {row.map((cell, j) => (
                          <td key={`${key}-r${r}-${j}`}>{inline(cell, `${key}-r${r}-${j}`)}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            );
        }
      })}
    </>
  );
}
