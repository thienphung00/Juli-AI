// The popup's platform-free shell: the DOM lookup, the message to the service worker, the date
// format and opening a tab. A platform's popup page builds on it.

export function el<T extends HTMLElement>(id: string): T {
  const found = document.getElementById(id);
  if (!found) throw new Error(`#${id} missing`);
  return found as T;
}

export async function send<T>(message: Record<string, unknown>): Promise<T> {
  const reply = (await chrome.runtime.sendMessage(message)) as { ok: boolean; value?: T; error?: string };
  if (!reply?.ok) throw new Error(reply?.error ?? "Không gửi được");
  return reply.value as T;
}

export function fmt(iso: string | null): string {
  return iso ? new Date(iso).toLocaleString("vi-VN") : "chưa có";
}

export function openTab(url: string): void {
  void chrome.tabs.create({ url, active: true });
}
