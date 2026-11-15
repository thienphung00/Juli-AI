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

/**
 * Ask for the optional host permissions of a just-paired platform (manifest
 * `optional_host_permissions`); runs from the person's click on "Kết nối". Never throws.
 */
export async function requestHosts(origins: readonly string[] | undefined): Promise<boolean> {
  if (!origins || origins.length === 0) return true;
  try {
    return await chrome.permissions.request({ origins: [...origins] });
  } catch {
    return false;
  }
}

export function openTab(url: string): void {
  void chrome.tabs.create({ url, active: true });
}
