"use client";

import { useEffect, useMemo, useState } from "react";

import { DASH } from "../../lib/shopee-analytics/format";
import { useResource } from "../../lib/shopee-analytics/use-resource";
import { useReco } from "../../lib/shopee-decisions/context";
import { statusLabel } from "../../lib/shopee-decisions/model";
import type { CardByCode, CardList, CardSummary } from "../../lib/shopee-decisions/types";
import { PRODUCT_GROUPS, versionFlag, vnWhenFull } from "../../lib/shopee-decisions/versions";
import { Empty, Notice, TextChip } from "../shopee-analytics/ui";
import { StaffBar } from "./staff-bar";
import { NavLink, RecoState, errorText } from "./ui";

/**
 * Juli Ops · Đề xuất (`OpsDeXuat.dc.html`): the shop's cards with their code, product, family,
 * source (Juli / Thủ công), queue place, versions, plan code and status; filter by status, search by
 * code, and "Tra thẻ theo mã" for a whole code (`GET …/recommendations/code/{code}`). No export
 * button until the export exists.
 */

type Filter = "all" | "open" | "planned" | "measuring" | "done" | "dismissed";

const FILTERS: readonly (readonly [Filter, string])[] = [
  ["all", "Tất cả"],
  ["open", "Chờ duyệt"],
  ["planned", "Trong kế hoạch"],
  ["measuring", "Đang đo"],
  ["done", "Đã đo xong"],
  ["dismissed", "Đã bỏ qua"],
];

/** The artboard's status groups from the card status. */
export function filterOf(c: Pick<CardSummary, "status" | "verification">): Exclude<Filter, "all"> | null {
  switch (c.status) {
    case "draft":
    case "sent":
    case "changes_requested":
    case "approved":
      return "open";
    case "planned":
      return "planned";
    case "executed":
      return "measuring";
    case "measured":
      return "done";
    case "rejected":
    case "expired":
      return "dismissed";
    default:
      return null;
  }
}

const GROUP_NAME = new Map(PRODUCT_GROUPS);
const CODE_RE = /^JC-\d{4}-\d{4,}(-V[1-4])?$/i;

function whenText(iso: string | null | undefined): string {
  return iso ? vnWhenFull(iso) : DASH;
}

export function OpsRecoList() {
  const host = useReco();
  const [tick, setTick] = useState(0);
  const [filter, setFilter] = useState<Filter>("all");
  const [q, setQ] = useState("");
  const res = useResource<CardList>(() => host.reco.list({ queue: "all" }), `${host.shopKey}|ops-list|${tick}`);
  const [names, setNames] = useState<ReadonlyMap<string, string>>(new Map());
  useEffect(() => {
    let live = true;
    host.products?.().then((list) => live && setNames(new Map(list.map((p) => [p.id, p.name]))), () => undefined);
    return () => {
      live = false;
    };
    // One list per shop.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [host.shopKey]);
  return (
    <div className="sa-page" data-testid="ops-reco">
      <header className="sa-head">
        <div className="sa-eyebrow">{host.shopName ? `${host.shopName} › Shopee` : "Shopee"}</div>
        <div className="sa-head__line sq-head">
          <h1 className="sa-h1">Danh sách đề xuất</h1>
          <NavLink className="sa-btn sa-btn--s" href={host.href({ builder: true, from: "product" })} testId="ops-builder-link">
            + Tạo phương án thủ công
          </NavLink>
        </div>
      </header>
      <StaffBar onChanged={() => setTick((t) => t + 1)} />
      <RecoState resource={res}>
        {(data) => <Table cards={data.cards} filter={filter} names={names} onFilter={setFilter} onQuery={setQ} q={q} />}
      </RecoState>
    </div>
  );
}

function Table({ cards, filter, q, names, onFilter, onQuery }: { readonly cards: readonly CardSummary[]; readonly filter: Filter; readonly q: string; readonly names: ReadonlyMap<string, string>; readonly onFilter: (f: Filter) => void; readonly onQuery: (q: string) => void }) {
  const host = useReco();
  const needle = q.trim().toLowerCase();
  const rows = useMemo(() => cards.filter((c) => (filter === "all" || filterOf(c) === filter) && (c.code ?? "").toLowerCase().includes(needle)), [cards, filter, needle]);
  const whole = CODE_RE.test(q.trim());
  return (
    <>
      <div className="ol-filters" data-testid="ops-filters">
        <span className="sa-hint">Trạng thái:</span>
        {FILTERS.map(([k, label]) => (
          <button aria-pressed={filter === k} className={`sb-pill ${filter === k ? "sb-pill--on" : ""}`} key={k} onClick={() => onFilter(k)} type="button">
            {label}
          </button>
        ))}
        <label className="ol-search">
          Tìm theo mã <input onChange={(e) => onQuery(e.target.value)} placeholder="JC-2611-0007" type="search" value={q} />
        </label>
      </div>
      {whole ? <CodeLookup code={q.trim().toUpperCase()} /> : null}
      <div className="ol-table" data-testid="ops-table" role="table">
        <div className="ol-row ol-row--head" role="row">
          {["Mã thẻ", "Sản phẩm · thay đổi", "Họ", "Nguồn", "Hàng đợi", "Phiên bản", "Mã kế hoạch", "Trạng thái", "Tạo lúc"].map((h) => (
            <span key={h} role="columnheader">
              {h}
            </span>
          ))}
        </div>
        {rows.map((c) => (
          <div className="ol-row" data-testid={`ops-row-${c.code ?? c.id}`} key={c.id} role="row">
            <b role="cell">
              <NavLink href={host.href({ the: c.id })}>{c.code ?? c.id}</NavLink>
            </b>
            <span role="cell">
              <b>{c.title}</b>
              <span className="ol-sub">{(c.product_id && names.get(c.product_id)) || c.product_id || DASH}</span>
            </span>
            <span role="cell">{GROUP_NAME.get(c.family) ?? c.family_label}</span>
            <span role="cell">{c.origin === "manual" ? <TextChip tone="info">Thủ công</TextChip> : <TextChip tone="flat">Juli</TextChip>}</span>
            <span className={c.product_queue === 1 ? "ol-q1" : ""} role="cell">
              {c.product_queue ? `#${c.product_queue}` : DASH}
            </span>
            <span role="cell">{c.versions && c.versions.length > 0 ? `${c.versions.length} (V1 mặc định)` : DASH}</span>
            <span role="cell">{c.plan_code ?? (c.status === "planned" ? "Nháp, chưa có mã" : DASH)}</span>
            <span role="cell">
              <TextChip tone={c.status === "sent" || c.status === "changes_requested" ? "warn" : c.status === "planned" ? "pink" : c.status === "executed" || c.status === "approved" ? "info" : "flat"}>{statusLabel(c.status)}</TextChip>
            </span>
            <span role="cell">{whenText(c.sent_at)}</span>
          </div>
        ))}
        {rows.length === 0 ? <Empty testId="ops-empty">Không có thẻ khớp mã hoặc trạng thái này.</Empty> : null}
      </div>
      <p className="sa-hint ol-foot">Mã thẻ không bao giờ dùng lại trong cùng shop; thẻ trong kế hoạch đã xác nhận mang thêm mã kế hoạch KH-&lt;yymm&gt;-&lt;số&gt;. Phiên bản là mã thẻ thêm -V1 … -V4. Thẻ thay thế thẻ cũ khi sinh lại có liên kết tới mã cũ.</p>
    </>
  );
}

/** One card by its whole code: everything a row of the later export needs. */
function CodeLookup({ code }: { readonly code: string }) {
  const host = useReco();
  const [state, setState] = useState<{ readonly code: string; readonly data: CardByCode | null; readonly error: string | null } | null>(null);
  useEffect(() => {
    let live = true;
    host.reco.byCode(code).then(
      (data) => live && setState({ code, data, error: null }),
      (e: unknown) => live && setState({ code, data: null, error: errorText(e) }),
    );
    return () => {
      live = false;
    };
    // One read per code.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [code, host.shopKey]);
  if (!state || state.code !== code) {
    return (
      <p className="sa-hint" role="status">
        Đang tra {code}…
      </p>
    );
  }
  if (!state.data) {
    return (
      <Notice tone="warn" testId="ops-lookup-error">
        Không tìm thấy thẻ {code}. {state.error}
      </Notice>
    );
  }
  const d = state.data;
  const show = (o: unknown): string => (o && typeof o === "object" && Object.keys(o as object).length > 0 ? JSON.stringify(o) : DASH);
  return (
    <section className="sa-card" data-testid="ops-lookup">
      <div className="sa-card__head">
        <h2 className="sa-h2">Tra thẻ theo mã · {d.code}</h2>
        <NavLink className="sa-link" href={host.href({ the: d.id })}>
          Mở thẻ ›
        </NavLink>
      </div>
      <dl className="sd-why">
        <dt>Thẻ</dt>
        <dd>
          {d.title} · {statusLabel(d.status)} · hàng đợi {d.product_queue ? `#${d.product_queue}` : DASH}
          {d.supersedes_code ? ` · thay thẻ ${d.supersedes_code}` : ""}
        </dd>
        <dt>Phiên bản</dt>
        <dd>
          {d.versions.map((v) => (
            <span className="ol-ver" key={v.version}>
              {v.code ?? `V${v.version}`} · {v.label ?? DASH}
              {versionFlag(v) ? ` · ${versionFlag(v)}` : ""}
              {d.chosen_version === v.version ? " · đã chọn" : ""}
            </span>
          ))}
        </dd>
        <dt>Đầu vào</dt>
        <dd data-testid="ops-lookup-inputs">
          mặc định {show(d.inputs.default)} · đã chọn {show(d.inputs.chosen)} · đã duyệt {show(d.inputs.approved)}
        </dd>
        <dt>Thay đổi</dt>
        <dd>
          trước {show(d.change.before)} → sau {show(d.change.after)}
        </dd>
        <dt>Lịch sử trạng thái</dt>
        <dd>
          {d.status_history.map((h, i) => (
            <span className="ol-ver" key={i}>
              {whenText(h.at)} · {h.event}
              {h.actor ? ` · ${h.actor}` : ""}
            </span>
          ))}
        </dd>
        <dt>Xác minh</dt>
        <dd>{d.verification.state ?? DASH}</dd>
      </dl>
    </section>
  );
}
