// What the service worker hands the content script for one card (the answer of Juli's
// GET /v1/ingest/fill/{code}), validated field by field: the page only ever sees plain strings.

export type FillKey = "title" | "description_first_line";
export type FillMode = "replace" | "first_line";

export interface FillField {
  key: FillKey;
  label: string;
  value: string;
  mode: FillMode;
  maxChars: number;
}

export interface FillStep {
  order: number;
  field: string;
  after: string | null;
  copy: string | null;
}

export interface FillRequest {
  code: string;
  itemId: string;
  changeKind: string;
  title: string;
  fields: FillField[];
  downloads: { label: string; url: string }[];
  steps: FillStep[];
  checklist: FillStep[];
  pageOnly: boolean;
  dependencies: string[];
}

const MAX_TEXT = 600;
const KEYS: readonly FillKey[] = ["title", "description_first_line"];
const MODES: readonly FillMode[] = ["replace", "first_line"];
const isRecord = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);
const text = (v: unknown, max = MAX_TEXT): string | undefined =>
  typeof v === "string" && v.length <= max ? v : undefined;

function step(raw: unknown): FillStep | undefined {
  if (!isRecord(raw)) return undefined;
  const field = text(raw.field, 200);
  if (field === undefined) return undefined;
  const after = raw.after === null || raw.after === undefined ? null : (text(raw.after, 2000) ?? null);
  const copy = raw.copy === null || raw.copy === undefined ? null : (text(raw.copy, 2000) ?? null);
  return { order: typeof raw.order === "number" ? raw.order : 0, field, after, copy };
}

/** The server's answer as a FillRequest, or null when anything is off (nothing is filled then). */
export function parseFillRequest(raw: unknown): FillRequest | null {
  if (!isRecord(raw)) return null;
  const code = text(raw.code, 40);
  const itemId = text(raw.item_id, 20);
  const changeKind = text(raw.change_kind, 40);
  if (!code || !itemId || !/^\d+$/.test(itemId) || !changeKind) return null;
  const fields: FillField[] = [];
  for (const f of Array.isArray(raw.fields) ? raw.fields : []) {
    if (!isRecord(f)) return null;
    const key = f.key as FillKey;
    const mode = f.mode as FillMode;
    const value = text(f.value);
    const label = text(f.label, 80);
    const maxChars = typeof f.max_chars === "number" ? f.max_chars : 0;
    if (!KEYS.includes(key) || !MODES.includes(mode) || !value || !label || maxChars < 1) return null;
    if (value.length > maxChars || value.includes("\r")) return null;
    if (key === "title" && value.includes("\n")) return null;
    if (key === "description_first_line" && value.includes("\n")) return null;
    fields.push({ key, label, value, mode, maxChars });
  }
  const downloads: { label: string; url: string }[] = [];
  for (const d of Array.isArray(raw.downloads) ? raw.downloads : []) {
    if (!isRecord(d)) continue;
    const url = text(d.url, 1000);
    if (url !== undefined && /^https:\/\/[^\s]+$/i.test(url)) downloads.push({ label: text(d.label, 80) ?? "Tải ảnh", url });
  }
  const steps = (Array.isArray(raw.steps) ? raw.steps : []).map(step).filter((s): s is FillStep => !!s);
  const checklist = (Array.isArray(raw.checklist) ? raw.checklist : []).map(step).filter((s): s is FillStep => !!s);
  const dependencies = (Array.isArray(raw.dependencies) ? raw.dependencies : []).filter(
    (d): d is string => typeof d === "string" && d.length <= 40,
  );
  return {
    code,
    itemId,
    changeKind,
    title: text(raw.title, 300) ?? code,
    fields,
    downloads,
    steps,
    checklist,
    pageOnly: raw.page_only === true,
    dependencies,
  };
}

/** The reply of the service worker to the content script's fill-request message. */
export type FillReply =
  | { ok: true; value: FillRequest }
  | { ok: false; reason: FillRefusal };

/** `inactive`: flag / pilot gate (stay invisible); the others are shown in the panel. */
export type FillRefusal = "inactive" | "unpaired" | "disabled" | "not_found" | "not_approved" | "unsupported" | "wrong_item" | "error";
