"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { ShopeeApiError } from "../../lib/shopee-analytics/client";
import { DASH, fmt, vnd } from "../../lib/shopee-analytics/format";
import { useResource } from "../../lib/shopee-analytics/use-resource";
import { useReco } from "../../lib/shopee-decisions/context";
import { changedInputs, describeInputs, maxInputsFor, rankingLinkOf, stepText } from "../../lib/shopee-decisions/model";
import type { Breach, Card, CardDetail, CardSummary, CardVersion, ExecutionSheet } from "../../lib/shopee-decisions/types";
import {
  MAX_TITLE_CHARS,
  ackOf,
  ackText,
  breachNoun,
  breachWarnLines,
  breachesOf,
  cardOfVersion,
  isOpen,
  isRefused,
  isTitleKind,
  measuringDaysLeft,
  measuringNote,
  queueLabel,
  titleCount,
  titleOf,
  versionCode,
  versionName,
  versionsOf,
} from "../../lib/shopee-decisions/versions";
import { Notice, TextChip } from "../shopee-analytics/ui";
import { DismissDialog, RequestChangeDialog } from "./dialogs";
import { ExecutionPanel, READ_ONLY_TITLE } from "./execution";
import { MegaPanel } from "./mega";
import { Checks, NumbersTable } from "./numbers";
import { NavLink, RecoState, StatusChip, errorText } from "./ui";
import { WhatIfPanel, type Patch } from "./whatif";
import { BreachDialog, TitleBox, VersionsTable } from "./versions";

/**
 * One Shopee card (artboards `CardWhatIf.dc.html` and, since P91, `CardVersions.dc.html`): 2-4 versions
 * side by side, what the selected version changes, its what-if inputs, the checks (floor, spend cap,
 * break-even), the five numbers in two layers, why, and the decision. A floor or spend-cap breach never
 * disables a button: it opens a warning whose "Vẫn tiếp tục" is recorded. An approved card turns into
 * the assisted-execution sheet.
 */

type Outcome = { readonly kind: "approved" | "requested" | "dismissed" | "executed" | "sent" | "withdrawn"; readonly text: string; readonly more?: string; readonly ack?: string };

const ADJUSTABLE = new Set(["draft", "sent", "changes_requested"]);
const NO_PATCH: Patch = {};
const BREACH_CODES = new Set(["reco_breach_unacknowledged", "reco_breach_not_acknowledged"]);

export function CardPage({ id, from, version = null }: { readonly id: string; readonly from: string | null; readonly version?: number | null }) {
  const host = useReco();
  const [tick, setTick] = useState(0);
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const res = useResource(() => host.reco.detail(id), `${host.shopKey}|card|${id}|${tick}`);
  const backTo = from === "phan-tich" ? host.links.critical() : from === "xep-hang" ? host.links.ranking() : from === "san-pham" ? host.links.products() : from === "tong-quan" ? host.links.overview() : null;
  return (
    <div className="sa-page" data-testid="sd-card-page">
      <nav className="sd-back">
        <NavLink href={host.href({})}>‹ Danh sách đề xuất</NavLink>
        {backTo ? (
          <a className="sa-link" href={backTo}>
            Về {from === "phan-tich" ? "Phân tích" : from === "xep-hang" ? "Xếp hạng" : from === "san-pham" ? "Sản phẩm" : "Tổng quan"}
          </a>
        ) : null}
      </nav>
      {outcome ? (
        <Notice tone="info" testId="sd-outcome">
          <span>{outcome.text}</span>
          {outcome.more ? <span className="sd-outcome__more"> {outcome.more}</span> : null}
          {outcome.ack ? (
            <b className="sd-ack" data-testid="sd-ack">
              {" "}
              {outcome.ack}
            </b>
          ) : null}
        </Notice>
      ) : null}
      <RecoState resource={res}>
        {(detail) => (
          <CardBody
            detail={detail}
            initial={version}
            key={`${id}|${tick}`}
            onChanged={(o) => {
              setOutcome(o);
              setTick((t) => t + 1);
            }}
          />
        )}
      </RecoState>
    </div>
  );
}

/** Which version the approval was for: the backend's `chosen_version`, else the one whose inputs match what was approved. */
function chosenIndex(detail: CardDetail, versions: readonly CardVersion[]): number {
  if (typeof detail.chosen_version === "number") return Math.min(Math.max(detail.chosen_version - 1, 0), versions.length - 1);
  const approved = detail.approved_with?.inputs;
  if (approved) {
    const hit = versions.findIndex((v) => JSON.stringify(v.inputs) === JSON.stringify(approved));
    if (hit >= 0) return hit;
  }
  return 0;
}

/** The card the seller approved: the final values' recompute, when the API did not send their sheet. */
function useFinalCard(detail: CardDetail, chosen: number): { readonly card: Card; readonly sheet: ExecutionSheet; readonly note: string | null } {
  const host = useReco();
  const open = detail.status === "approved" || detail.status === "executed";
  const approved = detail.approved_with;
  const versions = versionsOf(detail.card);
  const base = versions[chosen] ?? versions[0]!;
  const differs = open && approved !== undefined && !approved.execution_sheet && Object.keys(changedInputs(base.inputs, approved.inputs)).length > 0;
  const [recomputed, setRecomputed] = useState<{ readonly card: Card | null; readonly failed: boolean } | null>(null);
  useEffect(() => {
    if (!differs || !approved) return;
    let live = true;
    host.reco
      .whatif(detail.id, approved.inputs, chosen + 1)
      .then((card) => live && setRecomputed({ card, failed: false }))
      .catch(() => live && setRecomputed({ card: null, failed: true }));
    return () => {
      live = false;
    };
    // The approved values are fixed for this detail.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [detail.id, differs]);
  const card = recomputed?.card ?? cardOfVersion(detail.card, base);
  return {
    card,
    sheet: approved?.execution_sheet ?? card.execution_sheet,
    note: differs && recomputed?.failed ? "Bảng thao tác theo thẻ gốc: chưa tính lại được theo giá trị bạn đã duyệt. Hỏi đội Juli nếu số khác với bạn đã chọn." : null,
  };
}

/** The product's other open cards (the queue behind this one): "Tiếp theo cho sản phẩm này". */
function useQueue(detail: CardDetail): readonly CardSummary[] | null {
  const host = useReco();
  const pid = detail.product_id ?? null;
  const res = useResource<readonly CardSummary[]>(async () => (pid ? (await host.reco.list({ productId: pid, queue: "all" })).cards : []), `${host.shopKey}|queue|${pid}|${detail.id}|${detail.status}`);
  return res.status === "ready" ? res.data : null;
}

function nextCard(detail: CardDetail, queue: readonly CardSummary[] | null): { readonly next: CardSummary | null; readonly open: readonly CardSummary[] } {
  const open = (queue ?? []).filter(isOpen).sort((a, b) => (a.product_queue ?? 1e6) - (b.product_queue ?? 1e6));
  const mine = detail.product_queue ?? null;
  const next = mine === 1 ? (open.find((c) => c.product_queue === 2) ?? null) : (open.find((c) => c.product_queue === 1 && c.id !== detail.id) ?? null);
  return { next, open };
}

const dmy = (iso: string): string => `${iso.slice(8, 10)}/${iso.slice(5, 7)}/${iso.slice(0, 4)}`;

function todayText(card: Card): string {
  if (isTitleKind(card)) return "tiêu đề hiện tại";
  const b = card.change.before as { value?: unknown; min_spend?: unknown };
  if (typeof b.value === "number" && typeof b.min_spend === "number") return `voucher hiện tại: ${vnd(b.value)} cho đơn ≥ ${vnd(b.min_spend)}`;
  return "trước khi đổi";
}

function CardBody({ detail, initial, onChanged }: { readonly detail: CardDetail; readonly initial: number | null; readonly onChanged: (o: Outcome) => void }) {
  const host = useReco();
  const queue = useQueue(detail);
  const { next, open } = nextCard(detail, queue);
  const adjustable = ADJUSTABLE.has(detail.status);
  const seller = !host.readOnly && !host.staff;
  const baseVersions = useMemo(() => versionsOf(detail.card), [detail.card]);
  const chosen = chosenIndex(detail, baseVersions);
  const final = useFinalCard(detail, chosen);
  const [versions, setVersions] = useState<readonly CardVersion[]>(baseVersions);
  const [megaFresh, setMegaFresh] = useState<Card | null>(null);
  const [sel, setSel] = useState(() => (initial && initial >= 1 && initial <= baseVersions.length ? initial - 1 : adjustable ? Math.max(0, baseVersions.findIndex((v) => !isRefused(v))) : chosen));
  const [patches, setPatches] = useState<Readonly<Record<number, Patch>>>({});
  const [calc, setCalc] = useState<"idle" | "busy" | "error">("idle");
  const [error, setError] = useState<string | null>(null);
  const [dialog, setDialog] = useState<"dismiss" | "request" | null>(null);
  const [warn, setWarn] = useState<{ readonly breaches: readonly Breach[] } | null>(null);
  const [busy, setBusy] = useState(false);
  const seq = useRef(0);
  const timer = useRef<number | null>(null);
  useEffect(
    () => () => {
      if (timer.current !== null) window.clearTimeout(timer.current);
    },
    [],
  );

  const v = versions[sel] ?? versions[0]!;
  const patch: Patch = patches[sel] ?? NO_PATCH;
  const shown = adjustable ? (detail.card.family === "mega_sale" ? (megaFresh ?? detail.card) : cardOfVersion(detail.card, v)) : final.card;
  const isMega = shown.family === "mega_sale";
  const title = isTitleKind(shown);
  const name = versionName(v);
  const vcode = versionCode(detail.card, v);
  const refused = isRefused(v);

  const change = (nextPatch: Patch) => {
    const index = sel;
    setPatches((p) => ({ ...p, [index]: nextPatch }));
    setCalc("busy");
    setError(null);
    if (timer.current !== null) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => {
      const n = ++seq.current;
      host.reco
        .whatif(detail.id, nextPatch, index + 1)
        .then((c) => {
          if (n !== seq.current) return;
          if (c.family === "mega_sale") setMegaFresh(c);
          const fresh = versionsOf(c)[index];
          if (fresh) setVersions((cur) => cur.map((x, i) => (i === index ? fresh : x)));
          setCalc("idle");
        })
        .catch((e: unknown) => {
          if (n !== seq.current) return;
          setCalc("error");
          setError(errorText(e));
        });
    }, 300);
  };
  const pick = (index: number) => {
    setSel(index);
    setError(null);
    setCalc("idle");
  };
  const reset = () => {
    const index = sel;
    setPatches((p) => {
      const { [index]: _gone, ...rest } = p;
      void _gone;
      return rest;
    });
    const orig = baseVersions[index];
    if (orig) setVersions((cur) => cur.map((x, i) => (i === index ? orig : x)));
    setCalc("idle");
    setError(null);
  };

  const [titleDraft, setTitleDraft] = useState<Readonly<Record<number, string>>>({});
  const titleText = title ? (titleDraft[sel] ?? titleOf(v.inputs)) : "";
  const count = titleCount(titleText);
  const onTitle = (text: string) => {
    setTitleDraft((d) => ({ ...d, [sel]: text }));
    // Above 100 characters nothing is sent (D-4); the counter and the locked button say why.
    if (text.length > 0 && text.length <= MAX_TITLE_CHARS) change({ ...patch, title: text });
    else {
      setPatches((p) => ({ ...p, [sel]: { ...patch, title: text } }));
    }
  };

  const sliders = shown.whatif.sliders;
  const viewing = describeInputs(shown, sliders);
  const sent = (detail.status === "sent" || detail.status === "changes_requested") && seller;
  const canDecide = detail.status === "sent" && seller;
  const breaches = breachesOf(shown);
  const stale = calc === "busy";
  const stored = baseVersions[sel]?.inputs ?? detail.card.inputs;
  const sendInputs = useMemo(() => {
    const diff = isMega ? { ...patch } : changedInputs(stored, patch);
    if (isMega && Array.isArray(diff["remove"]) && (diff["remove"] as unknown[]).length === 0) delete diff["remove"];
    return Object.keys(diff).length > 0 ? diff : null;
  }, [patch, stored, isMega]);
  const maxInputs = breaches.some((b) => b.type === "floor") ? maxInputsFor(shown) : null;
  const rank = rankingLinkOf(detail);
  const productId = detail.scope.product_ids[0] ?? detail.product_id ?? null;
  const edited = sendInputs !== null;
  const ack = ackOf(detail);

  const run = async (kind: Outcome["kind"], outcome: Omit<Outcome, "kind">, call: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await call();
      setDialog(null);
      setWarn(null);
      onChanged({ kind, ...outcome });
    } catch (e) {
      if (e instanceof ShopeeApiError && BREACH_CODES.has(e.code) && Array.isArray(e.detail?.["breaches"])) {
        setWarn({ breaches: e.detail["breaches"] as Breach[] });
      } else {
        setError(errorText(e));
      }
    } finally {
      setBusy(false);
    }
  };

  const approveOutcome = (acknowledged: readonly Breach[]): Omit<Outcome, "kind"> => {
    const days = shown.measurement_plan.planned_days;
    return {
      text: `Đã duyệt ${vcode}. Các phiên bản còn lại đóng cùng thẻ. Đội Juli đặt thay đổi trên Seller Centre, bạn xác nhận lần cuối trước khi áp dụng.`,
      more: `${next ? `Thẻ kế tiếp của sản phẩm (${next.code ?? next.id}) đã lên Quyết định ngay. ` : ""}Sản phẩm này sẽ được đo: kết quả đọc sau ${days === null ? "…" : fmt(days, 0)} ngày; thẻ mới của sản phẩm vẫn duyệt được trong lúc đo (xem “Sản phẩm đang đo”).`,
      ack: acknowledged.length > 0 ? ackText(acknowledged, new Date().toISOString()) : undefined,
    };
  };
  const approve = (acknowledge: boolean, shownBreaches: readonly Breach[]) =>
    run("approved", approveOutcome(acknowledge ? shownBreaches : []), () => host.reco.approve(detail.id, { inputs: sendInputs, chosenVersion: v.version, acknowledgeBreaches: acknowledge }));
  const onApprove = () => (breaches.length > 0 ? setWarn({ breaches }) : void approve(false, []));

  const approveOff = !canDecide || busy || stale || calc === "error" || refused || (title && count.over) || (title && count.n === 0);
  const hint = title && count.over
    ? `Rút bớt ${count.n - MAX_TITLE_CHARS} ký tự để duyệt.`
    : breaches.length > 0
      ? `${name} ${breachNoun(breaches)}: vẫn duyệt được, Juli sẽ hiện cảnh báo trước.`
      : edited
        ? "Duyệt giá trị bạn đã chỉnh. Juli ghi lại thay đổi của bạn."
        : "Duyệt cả phiên bản như đang hiển thị.";
  const measuring = detail.product_measuring ?? null;
  const left = measuringDaysLeft(measuring, host.now?.() ?? new Date());
  const queueTotal = open.length;

  return (
    <>
      <header className="sa-head">
        <div className="sa-eyebrow">QUYẾT ĐỊNH · ĐỀ XUẤT · {detail.family_label.toUpperCase()}</div>
        <div className="sa-head__line">
          {detail.code ? (
            <span className="sd-code" data-testid="sd-code">
              {detail.code}
            </span>
          ) : null}
          {detail.product_id ? <span className="sa-chip sa-chip--outline">SP · {detail.product_id}</span> : null}
          <h1 className="sa-h1 sa-h1--title">{detail.title}</h1>
          <StatusChip status={detail.status} />
          {detail.bundle ? <TextChip tone="info">Đo như một gói</TextChip> : null}
        </div>
        <p className="sa-hint" data-testid="sd-queue-line">
          {detail.product_queue ? <b>{queueLabel(detail.product_queue)}</b> : null}
          {detail.product_queue ? " · " : ""}
          {detail.family_label} · cập nhật {dmy(shown.as_of)} · {fmt(versions.length, 0)} phiên bản{detail.product_queue && queueTotal > 0 ? ` · thẻ ${detail.product_queue} trong ${queueTotal} thẻ của sản phẩm này` : ""}
        </p>
        <p className="sa-hint">
          Tính trên {fmt(shown.window.days, 0)} ngày đến {shown.window.to.slice(8, 10)}/{shown.window.to.slice(5, 7)} · {shown.order_basis.label} · Kế hoạch đo: {shown.measurement_plan.label}
        </p>
      </header>

      {detail.product_id && (next || detail.product_queue) ? (
        <div className="sd-next" data-testid="sd-next">
          <b>Tiếp theo cho sản phẩm này:</b>
          {next ? (
            <>
              <span className="sd-code">{next.code ?? next.id}</span>
              <span>
                {next.title}
                {detail.product_queue === 1 ? ` · còn ${Math.max(0, queueTotal - 1)} thẻ xếp hàng` : ` · đang ở Quyết định; thẻ này lên sau khi ${Math.max(0, (detail.product_queue ?? 1) - 1)} thẻ trước đóng`}
              </span>
            </>
          ) : (
            <span>Không còn thẻ xếp hàng.</span>
          )}
          <NavLink className="sa-link" href={host.links.product(detail.product_id, { tab: "dx", from: "card", card: detail.id })}>
            Xem cả hàng đợi ›
          </NavLink>
        </div>
      ) : null}

      {measuring && left > 0 && adjustable ? (
        <div className="sd-measuring" data-testid="sd-measuring" role="status">
          <b>Sản phẩm đang đo: còn {left} ngày</b>
          <span>{measuringNote(measuring)}</span>
        </div>
      ) : null}

      {detail.stale ? (
        <Notice tone="warn" testId="sd-stale">
          <b>Thông số shop vừa đổi.</b> Thẻ này sẽ được tính lại; số bên dưới là số của lần tính trước.
        </Notice>
      ) : null}
      {detail.status === "draft" ? <Notice tone="info">Nháp: shop chưa thấy thẻ này.</Notice> : null}
      {detail.status === "changes_requested" ? <Notice tone="info">Shop đã yêu cầu chỉnh thẻ này. Đội Juli tính lại và gửi thẻ mới.</Notice> : null}
      {final.note ? <Notice tone="warn">{final.note}</Notice> : null}
      {ack ? (
        <p className="sd-ack-line" data-testid="sd-ack-card">
          <b className="sd-ack">{ackText(ack.breaches, ack.at)}</b>
        </p>
      ) : null}

      {detail.status === "approved" || detail.status === "executed" ? <ExecutionPanel detail={detail} onExecuted={() => onChanged({ kind: "executed", text: "Đã ghi nhận “Đã làm”. Juli sẽ đọc lại trên Seller Centre để xác minh." })} sheet={final.sheet} /> : null}

      {!isMega ? <VersionsTable card={detail.card} locked={!adjustable} onPick={pick} sel={sel} todayText={todayText(shown)} versions={versions} /> : null}

      {refused ? (
        <Notice tone="warn" testId="sd-refused">
          {name} chưa tính được{v.refusal ? `: ${v.refusal}` : ""}. Chọn phiên bản khác để duyệt.
        </Notice>
      ) : (
        <section className="sa-card" data-testid="sd-changes">
          <div className="sa-card__head">
            <h2 className="sa-h2">Thay đổi đề xuất</h2>
            <span className="sa-hint">Juli không tự sửa Seller Centre: bạn làm theo bảng thao tác sau khi duyệt.</span>
          </div>
          <div className="sa-chips">
            {shown.execution_sheet.steps.map((s) => (
              <span className="sa-chips__item" key={s.order}>
                {s.field}: {stepText(s.before, s.unit)} → <b>{stepText(s.after, s.unit)}</b>
              </span>
            ))}
          </div>
          <dl className="sd-why">
            <dt>Lý do</dt>
            <dd data-testid="sd-why">
              {detail.reason ?? DASH}{" "}
              <a className="sa-link" href={host.links.ranking(rank)}>
                Xem phân tích ›
              </a>
              {productId ? (
                <>
                  {" "}
                  <a className="sa-link" href={host.links.product(productId, { from: "card", card: detail.id })}>
                    Mở sản phẩm ›
                  </a>
                </>
              ) : null}
            </dd>
            <dt>Phiên bản đang chọn</dt>
            <dd data-testid="sd-selected">
              <b>{vcode}</b> <span className="sa-hint">Mã này được ghi vào quyết định (chosen_version) và nhật ký thẻ.</span>
            </dd>
          </dl>
        </section>
      )}

      {!refused ? (
        <section className="sa-card" data-testid="sd-inputs">
          <div className="sa-card__head">
            <h2 className="sa-h2">{isMega ? "Các thay đổi trong chiến dịch" : `Phép thử “nếu đổi” cho ${name}`}</h2>
            <span className="sa-hint">{adjustable ? (isMega ? "Mỗi lần đổi, mọi con số tính lại." : `Chỉ ${name} thay đổi, các phiên bản khác giữ nguyên.`) : `Giá trị ${detail.status === "rejected" ? "của thẻ" : "đã duyệt"}: ${viewing || DASH}`}</span>
            {adjustable && edited && !host.readOnly ? <TextChip tone="pink">Đã chỉnh so với đề xuất (whatif_adjusted)</TextChip> : null}
            {adjustable && edited && !host.readOnly ? (
              <button className="sa-btn sa-btn--s" disabled={!seller} onClick={reset} type="button">
                Về mặc định
              </button>
            ) : null}
            {stale ? (
              <span className="sa-hint" role="status">
                Đang tính lại…
              </span>
            ) : null}
          </div>
          {isMega ? <MegaPanel card={shown} disabled={!adjustable} editable={adjustable && shown.whatif.children_editable !== false} onChange={change} patch={patch} /> : title ? <TitleBox current={titleOf(detail.card.change.before as Record<string, unknown>) || "—"} disabled={!adjustable || !seller} name={name} onChange={onTitle} value={titleText} /> : adjustable ? <WhatIfPanel card={shown} disabled={!seller && !host.readOnly} onChange={change} patch={patch} /> : null}
          <Checks card={shown} />
          {breaches.length > 0 && adjustable && maxInputs ? (
            <div className="sd-lock" data-testid="sd-lock" role="status">
              <span>{name} {breachNoun(breaches)}: vẫn duyệt được sau khi bạn xác nhận cảnh báo.</span>
              <button className="sa-btn sa-btn--s" onClick={() => change({ ...patch, ...maxInputs })} type="button">
                Đặt về mức tối đa ({Object.entries(maxInputs).map(([k, val]) => (shown.whatif.sliders.find((x) => x.key === k)?.unit === "pct" ? `${fmt(val, 0)}%` : vnd(val))).join(", ")})
              </button>
            </div>
          ) : null}
        </section>
      ) : null}

      {!refused ? (
        <section className="sa-card" data-testid="sd-numbers-card">
          <NumbersTable card={shown} />
        </section>
      ) : null}

      {error ? (
        <p className="sd-error" role="alert">
          {error}
        </p>
      ) : null}

      {sent ? (
        <section className="sd-decision" data-testid="sd-decision">
          <button className="sa-btn sa-btn--primary" disabled={approveOff} onClick={onApprove} type="button">
            Duyệt {name}
          </button>
          {host.plan ? (
            <button className="sa-btn" data-testid="sd-add-plan" disabled={approveOff} onClick={() => void host.plan?.addCard(detail.id, v.version)} type="button">
              Thêm {name} vào kế hoạch
            </button>
          ) : null}
          <button className="sa-btn" disabled={!canDecide || busy || stale} onClick={() => setDialog("request")} type="button">
            Yêu cầu chỉnh
          </button>
          <button className="sa-btn" disabled={!canDecide || busy} onClick={() => setDialog("dismiss")} type="button">
            Bỏ qua
          </button>
          <span className={`sa-hint ${breaches.length > 0 ? "sd-hint--warn" : ""} ${title && count.over ? "sd-hint--bad" : ""}`} data-testid="sd-approve-hint">
            {hint}
          </span>
        </section>
      ) : null}
      {host.readOnly && adjustable ? (
        <p className="sa-hint" title={READ_ONLY_TITLE}>
          {READ_ONLY_TITLE}. Chỉ thử “nếu đổi” được, không ghi lại.
        </p>
      ) : null}

      {host.staff ? <StaffActions detail={detail} onChanged={onChanged} /> : null}

      <BreachDialog
        busy={busy}
        closing="Bạn vẫn có thể tiếp tục. Juli ghi lại rằng bạn đã xác nhận, kèm giờ, trên thẻ này."
        lines={warn ? breachWarnLines(warn.breaches) : []}
        onBack={() => setWarn(null)}
        onGo={() => void approve(true, warn?.breaches ?? [])}
        open={warn !== null}
        title={`Duyệt ${name} dù ${warn ? breachNoun(warn.breaches) : "chạm giá sàn"}?`}
      />
      <DismissDialog busy={busy} error={dialog === "dismiss" ? error : null} onCancel={() => setDialog(null)} onSubmit={(c) => void run("dismissed", { text: "Đã bỏ qua thẻ. Juli không đổi gì trên shop của bạn." }, () => host.reco.dismiss(detail.id, c))} open={dialog === "dismiss"} />
      <RequestChangeDialog
        busy={busy}
        error={dialog === "request" ? error : null}
        onCancel={() => setDialog(null)}
        onSubmit={(note) =>
          void run("requested", { text: `Đã gửi yêu cầu chỉnh với các giá trị bạn đang xem${viewing ? ` (${viewing})` : ""}. Đội Juli tính lại và gửi thẻ mới trong 1 ngày làm việc.` }, () =>
            host.reco.requestChange(detail.id, viewing ? `${note}\n\nGiá trị đang xem: ${viewing}` : note),
          )
        }
        open={dialog === "request"}
        viewing={viewing}
      />
    </>
  );
}

/** Juli Ops: send a draft to the shop, or take a card back. */
function StaffActions({ detail, onChanged }: { readonly detail: CardDetail; readonly onChanged: (o: Outcome) => void }) {
  const host = useReco();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const go = async (kind: Outcome["kind"], text: string, call: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await call();
      onChanged({ kind, text });
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  const canWithdraw = ["draft", "sent", "changes_requested", "approved"].includes(detail.status);
  return (
    <section className="sd-decision" data-testid="sd-staff">
      {detail.status === "draft" ? (
        <button className="sa-btn sa-btn--primary" disabled={busy} onClick={() => void go("sent", "Đã gửi thẻ cho shop.", () => host.reco.publish([detail.id]))} type="button">
          Gửi cho shop
        </button>
      ) : null}
      {canWithdraw ? (
        <button className="sa-btn" disabled={busy} onClick={() => void go("withdrawn", "Đã rút thẻ lại.", () => host.reco.withdraw(detail.id))} type="button">
          Rút lại
        </button>
      ) : null}
      {error ? (
        <span className="sd-error" role="alert">
          {error}
        </span>
      ) : null}
    </section>
  );
}
