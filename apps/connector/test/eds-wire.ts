// Minimal behaviour for the synthetic Seller Centre forms in test/fixtures/fill: what Shopee's
// eds-react components do when pressed (open a popper, toggle a switch, add a row, open a dialog,
// filter a table). Anything marked `data-forbidden` is a save / send / confirm button: pressing one
// is recorded in `wire.forbidden` so a test can assert it never happened.

export interface Wire {
  clicks: string[];
  forbidden: string[];
  stop(): void;
}

export function wireEds(doc: Document): Wire {
  const clicks: string[] = [];
  const forbidden: string[] = [];
  const onClick = (event: Event) => {
    const target = event.target as HTMLElement;
    clicks.push((target.textContent ?? target.getAttribute("aria-label") ?? target.tagName).trim().slice(0, 40));
    const bad = target.closest<HTMLElement>("[data-forbidden]");
    if (bad) {
      forbidden.push((bad.textContent ?? "").trim());
      return;
    }
    const sw = target.closest<HTMLElement>('[role="switch"]');
    if (sw) sw.setAttribute("aria-checked", sw.getAttribute("aria-checked") === "true" ? "false" : "true");
    const selector = target.closest<HTMLElement>(".eds-selector");
    if (selector && !target.closest(".eds-popper")) {
      doc.querySelectorAll(".eds-popper").forEach((p) => p.remove());
      const list = doc.createElement("ul");
      list.className = "eds-popper";
      for (const text of (selector.dataset.options ?? "").split("|")) {
        const li = doc.createElement("li");
        li.className = "eds-option";
        li.setAttribute("role", "option");
        li.textContent = text;
        li.addEventListener("click", () => {
          const inner = selector.querySelector(".eds-selector__inner");
          if (inner) inner.textContent = text;
          list.remove();
        });
        list.append(li);
      }
      doc.body.append(list);
    }
    const opens = target.closest<HTMLElement>("[data-opens]");
    if (opens) doc.querySelector(opens.dataset.opens!)?.removeAttribute("hidden");
    const add = target.closest<HTMLElement>("[data-add-row]");
    if (add) {
      const box = doc.querySelector(add.dataset.addRow!)!;
      box.append(box.firstElementChild!.cloneNode(true));
    }
    const search = target.closest<HTMLElement>("[data-search]");
    if (search) {
      const input = search.parentElement!.querySelector<HTMLInputElement>("input")!;
      doc.querySelectorAll<HTMLElement>(`${search.dataset.search} tr`).forEach((tr) => {
        if (input.value === "" || (tr.textContent ?? "").includes(input.value)) tr.removeAttribute("hidden");
        else tr.setAttribute("hidden", "");
      });
    }
  };
  doc.addEventListener("click", onClick);
  return { clicks, forbidden, stop: () => doc.removeEventListener("click", onClick) };
}
