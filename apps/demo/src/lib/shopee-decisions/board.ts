/**
 * Thực hiện board sync with work done outside Juli (owner decision 2026-11-16, backend S1
 * `api/routes/demo_shopee_board.py`): reset the board, and import the cards a shop already ran
 * from an xlsx (preview, then commit with the same file). The server checks the owner and refuses
 * the reviewer and the sample shop; the screens hide both actions there too.
 */

export type ExternalStatus = "done" | "running" | "proposed" | "cancelled" | "unknown";

export interface ExternalRow {
  readonly row: number;
  readonly ref: string;
  readonly category: string;
  readonly items: readonly string[];
  readonly shop_wide: boolean;
  readonly status: ExternalStatus;
  readonly status_label: string;
  readonly started_on: string | null;
  readonly run_days: number | null;
  readonly forecast_as_of: string | null;
  readonly skipped: boolean;
  readonly reason: string | null;
  readonly reason_label: string | null;
  readonly cards: readonly { readonly ref: string; readonly change_kind: string; readonly action: "create" | "exists" }[];
}

export interface ExternalPreview {
  readonly file_hash: string;
  readonly token: string;
  readonly missing_columns: readonly string[];
  readonly counts: { readonly rows: number; readonly cards: number; readonly create: number; readonly exists: number; readonly skipped: number };
  readonly rows: readonly ExternalRow[];
  readonly skipped: readonly ExternalRow[];
}

export interface ExternalCommit {
  readonly file_hash: string;
  readonly created: number;
  readonly exists: number;
  readonly refused: number;
  readonly skipped: number;
  readonly executed: number;
  readonly cards: readonly {
    readonly ref: string;
    readonly row: number;
    readonly change_kind: string;
    readonly status: string;
    readonly run_days: number | null;
    readonly action: "created" | "exists" | "refused";
    readonly card_id?: string;
    readonly code?: string;
    readonly executed_on?: string | null;
    readonly forecast_as_of?: string | null;
    readonly reason?: string | null;
    readonly message?: string | null;
  }[];
}

export interface BoardReset {
  readonly withdrawn: number;
  readonly by_status: Readonly<Record<string, number>>;
  readonly card_ids: readonly string[];
  readonly codes: readonly string[];
  readonly reason_code: "reset";
  readonly at: string;
}

export interface BoardApi {
  reset(note?: string | null): Promise<BoardReset>;
  previewImport(fileB64: string): Promise<ExternalPreview>;
  commitImport(fileB64: string, token: string): Promise<ExternalCommit>;
}

type Call = (method: "POST", path: string, body: unknown) => Promise<{ data: never }>;

export function boardApi(call: Call): BoardApi {
  return {
    reset: async (note) => (await call("POST", "/reset", { confirm: true, ...(note ? { note } : {}) })).data as BoardReset,
    previewImport: async (fileB64) => (await call("POST", "/external-import/preview", { file_b64: fileB64 })).data as ExternalPreview,
    commitImport: async (fileB64, token) => (await call("POST", "/external-import/commit", { file_b64: fileB64, token })).data as ExternalCommit,
  };
}

/** The refusals the board answers with, in the seller's words (the code is never shown). */
const ERROR_TEXT: Readonly<Record<string, string>> = {
  board_owner_only: "Chỉ chủ shop hoặc thành viên của shop làm được việc này.",
  board_reviewer_refused: "Không dùng được trên shop mẫu.",
  external_invalid_file: "File không đọc được. Chọn file .xlsx đúng mẫu.",
  external_file_changed: "File đã đổi sau khi xem trước. Chọn lại file.",
  external_nothing_to_import: "Không có thẻ mới để nhập.",
};

export function boardErrorText(e: unknown): string {
  const code = typeof e === "object" && e !== null && "code" in e ? String((e as { code: unknown }).code) : "";
  return ERROR_TEXT[code] ?? "Chưa làm được. Thử lại sau.";
}

/** The file as base64 (no data: prefix), as the routes take it. */
export async function fileToB64(file: Blob): Promise<string> {
  if (typeof file.arrayBuffer !== "function") {
    // older engines (and jsdom): FileReader, "data:…;base64," prefix dropped
    const url = await new Promise<string>((ok, bad) => {
      const r = new FileReader();
      r.onload = () => ok(String(r.result));
      r.onerror = () => bad(r.error);
      r.readAsDataURL(file);
    });
    return url.slice(url.indexOf(",") + 1);
  }
  const bytes = new Uint8Array(await file.arrayBuffer());
  let bin = "";
  for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(bin);
}
