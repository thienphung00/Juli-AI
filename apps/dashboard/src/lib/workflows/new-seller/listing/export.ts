import type { ProductDraft } from "@/lib/mock-data/listing-workflow/schemas";
import { canExportProductDraft } from "./export-guard";

export type ExportFormat = "json" | "csv";

export interface ExportResult {
  content: string;
  mimeType: string;
  filename: string;
}

export class ExportBlockedError extends Error {
  constructor(message = "Không thể xuất bản nháp bị chặn tuân thủ") {
    super(message);
    this.name = "ExportBlockedError";
  }
}

function assertExportable(draft: ProductDraft): void {
  if (!canExportProductDraft(draft)) {
    throw new ExportBlockedError();
  }
}

function sanitizeFilename(name: string): string {
  return name.replace(/[^\w\s-]/g, "").replace(/\s+/g, "_").slice(0, 80);
}

function buildFilename(draft: ProductDraft, extension: string): string {
  const base = sanitizeFilename(draft.product_info.product_name || draft.draft_id);
  return `${base}_${draft.draft_id.slice(0, 8)}.${extension}`;
}

function serializeJson(draft: ProductDraft): ExportResult {
  return {
    content: JSON.stringify(draft, null, 2),
    mimeType: "application/json",
    filename: buildFilename(draft, "json"),
  };
}

function escapeCsvCell(value: string): string {
  if (/[",\n\r]/.test(value)) {
    return `"${value.replace(/"/g, '""')}"`;
  }
  return value;
}

function flattenDraftToRow(draft: ProductDraft): Record<string, string> {
  const { product_info, listing_content, compliance, readiness } = draft;

  return {
    draft_id: draft.draft_id,
    seller_id: draft.seller_id,
    shop_id: draft.shop_id,
    status: draft.status,
    source_type: draft.source_type,
    "product_info.product_name": product_info.product_name,
    "product_info.brand": product_info.brand ?? "",
    "product_info.category": product_info.category,
    "product_info.price": String(product_info.price),
    "product_info.variants": product_info.variants.join("|"),
    "product_info.description": product_info.description ?? "",
    "listing_content.title": listing_content.title,
    "listing_content.description": listing_content.description,
    "listing_content.bullet_points": listing_content.bullet_points.join("|"),
    "listing_content.seo_keywords": listing_content.seo_keywords.join("|"),
    "listing_content.hashtags": listing_content.hashtags.join("|"),
    "compliance.status": compliance.status,
    "compliance.warnings": compliance.warnings.join("|"),
    "compliance.blocking_issues": compliance.blocking_issues.join("|"),
    "readiness.overall_score": String(readiness.overall_score),
    "readiness.suggested_improvements":
      readiness.suggested_improvements.join("|"),
    created_at: draft.created_at,
    updated_at: draft.updated_at,
  };
}

function serializeCsv(draft: ProductDraft): ExportResult {
  const row = flattenDraftToRow(draft);
  const headers = Object.keys(row);
  const values = headers.map((key) => escapeCsvCell(row[key] ?? ""));

  return {
    content: `${headers.join(",")}\n${values.join(",")}`,
    mimeType: "text/csv",
    filename: buildFilename(draft, "csv"),
  };
}

export function exportProductDraft(
  draft: ProductDraft,
  format: ExportFormat,
): ExportResult {
  assertExportable(draft);

  if (format === "json") {
    return serializeJson(draft);
  }

  return serializeCsv(draft);
}

/** Trigger a browser download from an export result (client-side only). */
export function downloadExportResult(result: ExportResult): void {
  if (typeof document === "undefined") return;

  const blob = new Blob([result.content], { type: result.mimeType });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = result.filename;
  anchor.click();
  URL.revokeObjectURL(url);
}
