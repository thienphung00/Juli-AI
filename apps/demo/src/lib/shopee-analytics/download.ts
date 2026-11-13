/** Writes a downloaded file through an object URL; a no-op where the browser API is missing (tests, old webviews). */
export function saveBlob(blob: Blob, name: string): void {
  if (typeof URL === "undefined" || typeof URL.createObjectURL !== "function") return;
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}

/** The file names of the two reports (the backend's `Content-Disposition` names). */
export function tongQuanFileName(shop: string, from: string, to: string, productId?: string | null): string {
  const day = (iso: string) => `${iso.slice(8, 10)}${iso.slice(5, 7)}${iso.slice(0, 4)}`;
  return `Juli_TongQuan_${shop.replace(/\s+/g, "")}${productId ? `_${productId}` : ""}_${day(from)}_${day(to)}.xlsx`;
}

export function keHoachFileName(shop: string, month: string): string {
  return `Juli_KeHoach_${shop.replace(/\s+/g, "")}_Tháng ${month.slice(5, 7)}-${month.slice(0, 4)}.xlsx`;
}
