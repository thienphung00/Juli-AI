// Phân tích Nội dung's empty day, read from the page as shown (Connector 0.3.32, batch-1123-a C3;
// captured read-only 2026-11-23: "0 Nội dung" above the table, "Không có dữ liệu" in the table).
//
// Strict on purpose: a day is empty only when the page's own count node says "0 Nội dung", or the
// content TABLE's own empty-state node says "Không có dữ liệu", AND no error / retry banner shows.
// The same words anywhere else (a toast, another widget, an error page) never make an empty day:
// the reader then ends needs_template, never "empty".

const COUNT_ZERO = /^0\s+Nội dung$/i;
const TABLE_EMPTY = /^Không có dữ liệu$/i;
const ERROR_TEXT = /Đã (xảy ra|có) lỗi|Có lỗi xảy ra|Lỗi (mạng|hệ thống|kết nối)|Thử lại|Tải lại|Something went wrong|Network error|Request failed/i;

const own = (el: Element): string => (el.textContent ?? "").replace(/\s+/g, " ").trim();
const leaves = (root: ParentNode): Element[] => Array.from(root.querySelectorAll("*")).filter((el) => el.children.length === 0);

/** An error / retry banner, a failed-request message or an error-classed node with text. */
export function errorBannerIn(doc: Document): boolean {
  if (leaves(doc).some((el) => ERROR_TEXT.test(own(el)))) return true;
  return Array.from(doc.querySelectorAll("[class*='error' i], [class*='exception' i], [role='alert']")).some((el) => own(el) !== "");
}

/** The content page's own count node reads "0 Nội dung", or its table's empty state reads "Không có dữ liệu". */
export function contentEmptyIn(doc: Document): boolean {
  if (errorBannerIn(doc)) return false;
  const countZero = leaves(doc).some((el) => COUNT_ZERO.test(own(el)));
  const tableEmpty = Array.from(doc.querySelectorAll("[class*='table' i] [class*='empty' i], table [class*='empty' i]")).some((el) =>
    TABLE_EMPTY.test(own(el)) || leaves(el).some((leaf) => TABLE_EMPTY.test(own(leaf))),
  );
  return countZero || tableEmpty;
}
