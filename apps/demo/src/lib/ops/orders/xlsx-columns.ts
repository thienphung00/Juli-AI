import { listZip, readEntry, ZipError, type ZipEntry } from "./zip";

/**
 * A column-selective `.xlsx` reader: the TypeScript twin of `xlsx.read_columns`. The FIRST row
 * is the header; `choose(header)` returns the header indexes whose values may be read (and may
 * throw to stop the load). The text of every other cell is never read: only the cell's position
 * (its `r` attribute) is looked at to decide that.
 */

const MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main";
const REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships";

export interface ColumnRead {
  readonly header: string[];
  /** One map per data row: header index -> cell text, for CHOSEN columns only. */
  readonly rows: Map<number, string | null>[];
  /** Header indexes whose cell VALUES were read, for the "no buyer column read" check. */
  readonly valueColumnsRead: Set<number>;
}

type Raw = readonly [kind: string | null, text: string | null];

function columnIndex(ref: string): number {
  const match = /^[A-Z]+/.exec(ref);
  if (!match) throw new ZipError("Tệp .xlsx bị hỏng.");
  let index = 0;
  for (const char of match[0]) index = index * 26 + char.charCodeAt(0) - 64;
  return index - 1;
}

function textOf(node: Element): string {
  return Array.from(node.getElementsByTagNameNS(MAIN, "t"))
    .map((t) => t.textContent ?? "")
    .join("");
}

function raw(cell: Element): Raw {
  const kind = cell.getAttribute("t");
  if (kind === "inlineStr") return [kind, textOf(cell)];
  const v = cell.getElementsByTagNameNS(MAIN, "v")[0];
  return [kind, v ? (v.textContent ?? null) : null];
}

function parseXml(bytes: Uint8Array): Document {
  const doc = new DOMParser().parseFromString(new TextDecoder("utf-8").decode(bytes), "application/xml");
  if (doc.getElementsByTagName("parsererror").length > 0) throw new ZipError("Tệp .xlsx bị hỏng.");
  return doc;
}

async function entryXml(bytes: Uint8Array, entries: Map<string, ZipEntry>, name: string): Promise<Document | null> {
  const entry = entries.get(name);
  return entry ? parseXml(await readEntry(bytes, entry)) : null;
}

async function sheetPath(bytes: Uint8Array, entries: Map<string, ZipEntry>, sheet: string): Promise<string> {
  const workbook = await entryXml(bytes, entries, "xl/workbook.xml");
  const rels = await entryXml(bytes, entries, "xl/_rels/workbook.xml.rels");
  if (!workbook || !rels) throw new ZipError("Tệp .xlsx bị hỏng.");
  const targets = new Map<string, string>();
  for (const rel of Array.from(rels.getElementsByTagName("Relationship"))) {
    targets.set(rel.getAttribute("Id") ?? "", rel.getAttribute("Target") ?? "");
  }
  for (const node of Array.from(workbook.getElementsByTagNameNS(MAIN, "sheet"))) {
    if (node.getAttribute("name") !== sheet) continue;
    const target = (targets.get(node.getAttributeNS(REL, "id") ?? "") ?? "").replace(/^\//, "");
    return target.startsWith("xl/") ? target : `xl/${target}`;
  }
  throw new ZipError(`Tệp không có trang "${sheet}".`);
}

/** Only the shared strings in `wanted` are decoded (the others are not read). */
async function neededStrings(bytes: Uint8Array, entries: Map<string, ZipEntry>, wanted: Set<number>): Promise<Map<number, string>> {
  const found = new Map<number, string>();
  if (wanted.size === 0) return found;
  const doc = await entryXml(bytes, entries, "xl/sharedStrings.xml");
  if (!doc) return found;
  const items = doc.getElementsByTagNameNS(MAIN, "si");
  for (const index of wanted) {
    const item = items[index];
    if (item) found.set(index, textOf(item));
  }
  return found;
}

export async function readColumns(bytes: Uint8Array, sheet: string, choose: (header: string[]) => Iterable<number>): Promise<ColumnRead> {
  const entries = listZip(bytes);
  const path = await sheetPath(bytes, entries, sheet);
  const entry = entries.get(path);
  if (!entry) throw new ZipError("Tệp .xlsx bị hỏng.");
  const doc = parseXml(await readEntry(bytes, entry));
  const rowNodes = Array.from(doc.getElementsByTagNameNS(MAIN, "row"));

  let header: string[] = [];
  let chosen = new Set<number>();
  const rawRows: Map<number, Raw>[] = [];
  const read = new Set<number>();
  const wanted = new Set<number>();
  for (const node of rowNodes) {
    const cells = Array.from(node.getElementsByTagNameNS(MAIN, "c"));
    if (header.length === 0) {
      if (cells.length === 0) continue;
      // Header cells are names, not data: all of them are read.
      const byIndex = new Map<number, Raw>();
      for (const cell of cells) byIndex.set(columnIndex(cell.getAttribute("r") ?? "A1"), raw(cell));
      const shared = new Set<number>();
      for (const [kind, text] of byIndex.values()) if (kind === "s" && text !== null) shared.add(Number(text));
      const names = await neededStrings(bytes, entries, shared);
      const width = Math.max(...byIndex.keys()) + 1;
      header = Array.from({ length: width }, (_, i) => {
        const [kind, text] = byIndex.get(i) ?? [null, null];
        const value = kind === "s" && text !== null ? (names.get(Number(text)) ?? "") : (text ?? "");
        return value.trim();
      });
      chosen = new Set(choose(header));
      continue;
    }
    const row = new Map<number, Raw>();
    for (const cell of cells) {
      const index = columnIndex(cell.getAttribute("r") ?? "A1");
      if (!chosen.has(index)) continue;
      const value = raw(cell);
      read.add(index);
      row.set(index, value);
      if (value[0] === "s" && value[1] !== null) wanted.add(Number(value[1]));
    }
    rawRows.push(row);
  }
  const strings = await neededStrings(bytes, entries, wanted);
  const rows = rawRows.map((row) => {
    const out = new Map<number, string | null>();
    for (const [index, [kind, text]] of row) {
      out.set(index, kind === "s" && text !== null ? (strings.get(Number(text)) ?? null) : text);
    }
    return out;
  });
  return { header, rows, valueColumnsRead: read };
}
