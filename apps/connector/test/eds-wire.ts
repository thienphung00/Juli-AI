// Minimal behaviour for the synthetic Seller Centre forms in test/fixtures/fill: what Shopee's
// eds-react components do when pressed (open a popper, toggle a switch, add a row, open a dialog,
// filter a table). Anything marked `data-forbidden` is a save / send / confirm button: pressing one
// is recorded in `wire.forbidden` so a test can assert it never happened.

export interface Wire {
  clicks: string[];
  forbidden: string[];
  stop(): void;
}

export function wireEds(doc: Document, opts: { datePicker?: boolean } = {}): Wire {
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
    const dismiss = target.closest<HTMLElement>("[data-dismiss]");
    if (dismiss) {
      // a notice's close: the notice goes, the page under it shows
      dismiss.closest('[role="dialog"]')?.remove();
      const under = doc.querySelector(dismiss.dataset.dismiss!);
      if (under instanceof HTMLTemplateElement) doc.body.append(under.content.cloneNode(true));
      else under?.removeAttribute("hidden");
    }
    const opens = target.closest<HTMLElement>("[data-opens]");
    if (opens) doc.querySelector(opens.dataset.opens!)?.removeAttribute("hidden");
    const add = target.closest<HTMLElement>("[data-add-row]");
    if (add) {
      const box = doc.querySelector(add.dataset.addRow!)!;
      box.append(box.firstElementChild!.cloneNode(true));
    }
    // 0.3.27 live shapes (synthetic, structure from the 2026-11-18 captures)
    const liveSelect = target.closest<HTMLElement>("[data-select-options]");
    if (liveSelect && !target.closest("[class*='select-options-list']")) {
      doc.querySelectorAll(".eds-react-select-options-list").forEach((p) => p.remove());
      const list = doc.createElement("div");
      list.className = "eds-react-select-options-list";
      for (const text of (liveSelect.dataset.selectOptions ?? "").split("|")) {
        const opt = doc.createElement("div");
        opt.className = "eds-react-select-option";
        opt.textContent = text;
        opt.addEventListener("click", () => {
          liveSelect.querySelector(".eds-react-select__inner")!.textContent = text;
          list.remove();
        });
        list.append(opt);
      }
      doc.body.append(list);
    }
    const pickerOk = target.closest<HTMLElement>("[data-picker-confirm]");
    if (pickerOk) {
      const modal = pickerOk.closest<HTMLElement>("[class*='product-selector']")!;
      const into = doc.querySelector(pickerOk.dataset.pickerConfirm!)!;
      modal.querySelectorAll<HTMLInputElement>("tbody tr input[type=checkbox]").forEach((c) => {
        if (c.checked) {
          const tr = doc.createElement("tr");
          tr.innerHTML = `<td>${c.closest("tr")!.querySelector(".name")!.textContent}</td><td>Mã: ${c.closest("tr")!.dataset.id}</td>`;
          into.append(tr);
        }
      });
      modal.setAttribute("hidden", "");
    }
    const nextPage = target.closest<HTMLElement>("[data-next-page]");
    if (nextPage) {
      const bodies = Array.from(doc.querySelectorAll<HTMLElement>(nextPage.dataset.nextPage!));
      const at = bodies.findIndex((b) => !b.hasAttribute("hidden"));
      if (at >= 0 && at + 1 < bodies.length) {
        bodies[at]!.setAttribute("hidden", "");
        bodies[at + 1]!.removeAttribute("hidden");
        if (at + 2 >= bodies.length) nextPage.classList.add("disabled");
      }
    }
    const search = target.closest<HTMLElement>("[data-search]");
    if (search && search.dataset.searchInput) {
      // the live picker: an id finds its row only under "Mã sản phẩm" (E48)
      const input = doc.querySelector<HTMLInputElement>(search.dataset.searchInput)!;
      const mode = doc.querySelector(search.dataset.searchMode ?? "")?.textContent ?? "";
      doc.querySelectorAll<HTMLElement>(`${search.dataset.search} tr`).forEach((tr) => {
        const hit = input.value === "" || (/Mã sản phẩm/.test(mode) ? tr.dataset.id === input.value : (tr.querySelector(".name")?.textContent ?? "").includes(input.value));
        if (hit) tr.removeAttribute("hidden");
        else tr.setAttribute("hidden", "");
      });
    } else if (search) {
      const input = search.parentElement!.querySelector<HTMLInputElement>("input")!;
      doc.querySelectorAll<HTMLElement>(`${search.dataset.search} tr`).forEach((tr) => {
        if (input.value === "" || (tr.textContent ?? "").includes(input.value)) tr.removeAttribute("hidden");
        else tr.setAttribute("hidden", "");
      });
    }
  };
  // "Thêm mức ưu đãi" carries the class `disabled` until the last tier has both values (live 2026-11-18)
  const onInput = () => {
    doc.querySelectorAll<HTMLElement>("[data-add-row][data-needs-filled]").forEach((add) => {
      const rows = Array.from(doc.querySelectorAll(`${add.dataset.addRow} tr`));
      const last = rows[rows.length - 1];
      const full = !!last && Array.from(last.querySelectorAll<HTMLInputElement>("input")).every((i) => i.value !== "");
      add.classList.toggle("disabled", !full);
    });
  };
  doc.addEventListener("click", onClick);
  doc.addEventListener("input", onInput, true);
  const stopPicker = opts.datePicker ? wireDatePicker(doc, clicks, forbidden) : () => undefined;
  return {
    clicks,
    forbidden,
    stop: () => {
      doc.removeEventListener("click", onClick);
      doc.removeEventListener("input", onInput, true);
      stopPicker();
    },
  };
}

/** Today in the synthetic date picker (days before it are disabled, like the live picker). */
export const PICKER_TODAY = { day: 18, month: 11, year: 2026 };

/**
 * Shopee's date-time picker as captured read-only on 2026-11-18 (structure only): a click on an
 * input of `.eds-date-picker` opens the popover (header month/year + arrows, a 6-week grid whose
 * leading / trailing days of the other months carry NO special class, past days `.disabled`, hour
 * and minute columns of `.time-box`, the picker's own Xác nhận in `__btn-wrap`). Xác nhận writes
 * `HH:mm DD-MM-YYYY` into the input (native setter + input/change, as React does) and closes.
 */
export function wireDatePicker(doc: Document, clicks: string[], forbidden: string[]): () => void {
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
  const onClick = (event: Event) => {
    const target = event.target as HTMLElement;
    const input = target.closest<HTMLInputElement>(".eds-date-picker input");
    if (!input || target.closest("[data-forbidden]")) return;
    if (input.closest(".eds-date-picker")?.hasAttribute("data-no-picker")) return;
    doc.querySelectorAll(".eds-react-date-picker__popup").forEach((p) => p.remove());
    const m = /^(\d{2}):(\d{2}) (\d{2})-(\d{2})-(\d{4})$/.exec(input.value);
    const state = {
      month: m ? Number(m[4]) : PICKER_TODAY.month,
      year: m ? Number(m[5]) : PICKER_TODAY.year,
      day: m ? Number(m[3]) : PICKER_TODAY.day,
      hh: m ? m[1]! : "19",
      mm: m ? m[2]! : "57",
      pickedMonth: m ? Number(m[4]) : PICKER_TODAY.month,
      pickedYear: m ? Number(m[5]) : PICKER_TODAY.year,
    };
    const pop = doc.createElement("div");
    pop.className = "eds-react-popover eds-react-date-picker__popup no-arrow";
    const draw = () => {
      const first = new Date(Date.UTC(state.year, state.month - 1, 1)).getUTCDay();
      const days = new Date(Date.UTC(state.year, state.month, 0)).getUTCDate();
      const prevDays = new Date(Date.UTC(state.year, state.month - 1, 0)).getUTCDate();
      const cells: { n: number; own: boolean }[] = [];
      for (let i = first - 1; i >= 0; i -= 1) cells.push({ n: prevDays - i, own: false });
      for (let d = 1; d <= days; d += 1) cells.push({ n: d, own: true });
      for (let d = 1; cells.length < 42; d += 1) cells.push({ n: d, own: false });
      const past = (n: number) => state.year * 10000 + state.month * 100 + n < PICKER_TODAY.year * 10000 + PICKER_TODAY.month * 100 + PICKER_TODAY.day;
      const rows: string[] = [];
      for (let r = 0; r < 6; r += 1) {
        rows.push(
          `<div class="eds-react-date-picker__table-row">${cells
            .slice(r * 7, r * 7 + 7)
            .map((c) => `<span class="eds-react-date-picker__table-cell-wrap"><span class="eds-react-date-picker__table-cell${c.own && past(c.n) ? " disabled" : ""}" data-own="${c.own ? 1 : 0}">${c.n}</span></span>`)
            .join("")}</div>`,
        );
      }
      const col = (n: number, sel: string) =>
        `<div class="eds-react-time-picker__tp-scrollbar"><span class="btn-op-time top"></span><div class="time-list-wrap"><ul class="time-list">${Array.from({ length: n }, (_, i) => String(i).padStart(2, "0"))
          .map((t) => `<li><span class="time-box${t === sel ? " selected" : ""}">${t}</span></li>`)
          .join("")}</ul></div><span class="btn-op-time bottom"></span></div>`;
      pop.innerHTML = `<div class="eds-react-popover-content"><div class="eds-react-popover-inner"><div class="eds-react-popover-inner-content">
        <div class="eds-react-date-picker__panel-wrap"><div class="eds-react-date-picker"><div class="eds-react-date-picker__box">
          <div class="eds-react-date-picker__panel">
            <div class="eds-react-date-picker__header">
              <span class="btn-arrow-default double" data-step="-12"><i class="icon-double-arrow-left"></i></span>
              <span class="btn-arrow-default" data-step="-1"><i class="icon-arrow-left"></i></span>
              <span class="date-box"><span class="date-default-style month">Th${state.month}</span> <span class="date-default-style year">${state.year}</span></span>
              <span class="btn-arrow-default" data-step="1"><i class="icon-arrow-right"></i></span>
              <span class="btn-arrow-default double" data-step="12"><i class="icon-double-arrow-right"></i></span>
            </div>
            <div class="eds-react-date-picker__table"><div class="eds-react-date-picker__table-header">${["CN", "T2", "T3", "T4", "T5", "T6", "T7"].map((d) => `<span class="eds-react-date-picker__table-cell">${d}</span>`).join("")}</div>${rows.join("")}</div>
          </div>
          <div class="eds-react-time-picker"><div class="eds-react-time-picker__panel col-2"><div class="selected-box"><span class="colon first-colon">:</span></div>${col(24, state.hh)}${col(60, state.mm)}</div></div>
        </div>
        <div class="eds-react-date-picker__btn-wrap"><button type="button" class="eds-react-button eds-react-button--primary eds-react-button--small"><span>Xác nhận</span></button></div>
        </div></div></div></div></div>`;
    };
    draw();
    pop.addEventListener("click", (e) => {
      e.stopPropagation();
      const t = e.target as HTMLElement;
      clicks.push((t.textContent ?? "").trim().slice(0, 40));
      const arrow = t.closest<HTMLElement>("[data-step]");
      if (arrow) {
        const total = state.year * 12 + (state.month - 1) + Number(arrow.dataset.step);
        state.year = Math.floor(total / 12);
        state.month = (total % 12) + 1;
        draw();
        return;
      }
      const cell = t.closest<HTMLElement>(".eds-react-date-picker__table-row .eds-react-date-picker__table-cell");
      if (cell && !cell.classList.contains("disabled")) {
        if (cell.dataset.own !== "1") return; // the live picker greys the other months' days
        state.day = Number(cell.textContent);
        state.pickedMonth = state.month;
        state.pickedYear = state.year;
        return;
      }
      const box = t.closest<HTMLElement>(".time-box");
      if (box) {
        const cols = Array.from(pop.querySelectorAll(".eds-react-time-picker__tp-scrollbar"));
        if (cols[0]!.contains(box)) state.hh = box.textContent!;
        else state.mm = box.textContent!;
        cols.forEach((c) => c.querySelectorAll(".time-box").forEach((b) => b.classList.toggle("selected", b.textContent === (cols[0] === c ? state.hh : state.mm))));
        return;
      }
      if (t.closest(".eds-react-date-picker__btn-wrap button")) {
        const v = `${state.hh}:${state.mm} ${String(state.day).padStart(2, "0")}-${String(state.pickedMonth).padStart(2, "0")}-${state.pickedYear}`;
        setter.call(input, v);
        input.dispatchEvent(new Event("input", { bubbles: true }));
        input.dispatchEvent(new Event("change", { bubbles: true }));
        pop.remove();
      }
    });
    doc.body.append(pop);
  };
  doc.addEventListener("click", onClick);
  void forbidden;
  return () => doc.removeEventListener("click", onClick);
}
