"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { DASH, fmt, vnd } from "../../lib/shopee-analytics/format";
import { useResource } from "../../lib/shopee-analytics/use-resource";
import { useReco } from "../../lib/shopee-decisions/context";
import { changedInputs, describeInputs, maxInputsFor, rankingLinkOf, stepText } from "../../lib/shopee-decisions/model";
import type { Card, CardDetail, ExecutionSheet } from "../../lib/shopee-decisions/types";
import { Notice, TextChip } from "../shopee-analytics/ui";
import { DismissDialog, RequestChangeDialog } from "./dialogs";
import { ExecutionPanel, READ_ONLY_TITLE } from "./execution";
import { MegaPanel } from "./mega";
import { Checks, NumbersTable } from "./numbers";
import { NavLink, RecoState, StatusChip, errorText } from "./ui";
import { WhatIfPanel, type Patch } from "./whatif";

/**
 * One Shopee card (artboard `CardWhatIf.dc.html`): what changes, the what-if inputs, the checks
 * (floor, spend cap, break-even), the five numbers in two layers, why, and the decision. An
 * approved card turns into the assisted-execution sheet.
 */

type Outcome = { readonly kind: "approved" | "requested" | "dismissed" | "executed" | "sent" | "withdrawn"; readonly text: string };

const ADJUSTABLE = new Set(["draft", "sent", "changes_requested"]);

export function CardPage({ id, from }: { readonly id: string; readonly from: string | null }) {
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
          {outcome.text}
        </Notice>
      ) : null}
      <RecoState resource={res}>
        {(detail) => (
          <CardBody
            detail={detail}
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

/** The card the seller approved: the final values' recompute, when the API did not send their sheet. */
function useFinalCard(detail: CardDetail): { readonly card: Card; readonly sheet: ExecutionSheet; readonly note: string | null } {
  const host = useReco();
  const open = detail.status === "approved" || detail.status === "executed";
  const approved = detail.approved_with;
  const differs = open && approved !== undefined && !approved.execution_sheet && Object.keys(changedInputs(detail.card.inputs, approved.inputs)).length > 0;
  const [recomputed, setRecomputed] = useState<{ readonly card: Card | null; readonly failed: boolean } | null>(null);
  useEffect(() => {
    if (!differs || !approved) return;
    let live = true;
    host.reco
      .whatif(detail.id, approved.inputs)
      .then((card) => live && setRecomputed({ card, failed: false }))
      .catch(() => live && setRecomputed({ card: null, failed: true }));
    return () => {
      live = false;
    };
    // The approved values are fixed for this detail.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [detail.id, differs]);
  const card = recomputed?.card ?? detail.card;
  return {
    card,
    sheet: approved?.execution_sheet ?? card.execution_sheet,
    note: differs && recomputed?.failed ? "Bảng thao tác theo thẻ gốc: chưa tính lại được theo giá trị bạn đã duyệt. Hỏi đội Juli nếu số khác với bạn đã chọn." : null,
  };
}

function CardBody({ detail, onChanged }: { readonly detail: CardDetail; readonly onChanged: (o: Outcome) => void }) {
  const host = useReco();
  const final = useFinalCard(detail);
  const adjustable = ADJUSTABLE.has(detail.status);
  const seller = !host.readOnly && !host.staff;
  const [card, setCard] = useState<Card>(detail.card);
  const [patch, setPatch] = useState<Patch>({});
  const [calc, setCalc] = useState<"idle" | "busy" | "error">("idle");
  const [error, setError] = useState<string | null>(null);
  const [dialog, setDialog] = useState<"dismiss" | "request" | null>(null);
  const [busy, setBusy] = useState(false);
  const seq = useRef(0);
  const timer = useRef<number | null>(null);
  useEffect(
    () => () => {
      if (timer.current !== null) window.clearTimeout(timer.current);
    },
    [],
  );

  const shown = adjustable ? card : final.card;
  const isMega = shown.family === "mega_sale";

  const change = (next: Patch) => {
    setPatch(next);
    setCalc("busy");
    setError(null);
    if (timer.current !== null) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => {
      const n = ++seq.current;
      host.reco
        .whatif(detail.id, next)
        .then((c) => {
          if (n !== seq.current) return;
          setCard(c);
          setCalc("idle");
        })
        .catch((e: unknown) => {
          if (n !== seq.current) return;
          setCalc("error");
          setError(errorText(e));
        });
    }, 300);
  };

  const sliders = shown.whatif.sliders;
  const viewing = describeInputs(shown, sliders);
  const sent = (detail.status === "sent" || detail.status === "changes_requested") && seller;
  const canDecide = detail.status === "sent" && seller;
  const floorLocked = !shown.floor.ok;
  const stale = calc === "busy";
  const sendInputs = useMemo(() => {
    const diff = isMega ? { ...patch } : changedInputs(detail.card.inputs, patch);
    if (isMega && Array.isArray(diff["remove"]) && (diff["remove"] as unknown[]).length === 0) delete diff["remove"];
    return Object.keys(diff).length > 0 ? diff : null;
  }, [patch, detail.card.inputs, isMega]);
  const maxInputs = floorLocked ? maxInputsFor(shown) : null;
  const rank = rankingLinkOf(detail);
  const productId = detail.scope.product_ids[0] ?? null;
  const edited = sendInputs !== null;

  const run = async (kind: Outcome["kind"], text: string, call: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await call();
      setDialog(null);
      onChanged({ kind, text });
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };

  const approve = () =>
    run("approved", "Đã duyệt. Thẻ chuyển sang Đang thực hiện: bạn làm theo bảng thao tác trên Seller Centre, rồi bấm “Đã làm”.", () => host.reco.approve(detail.id, { inputs: sendInputs }));

  return (
    <>
      <header className="sa-head">
        <div className="sa-eyebrow">QUYẾT ĐỊNH · ĐỀ XUẤT · {detail.family_label.toUpperCase()}</div>
        <div className="sa-head__line">
          <h1 className="sa-h1 sa-h1--title">{detail.title}</h1>
          <StatusChip status={detail.status} />
          {detail.bundle ? <TextChip tone="info">Đo như một gói</TextChip> : null}
        </div>
        <p className="sa-hint">
          Tính trên {fmt(shown.window.days, 0)} ngày đến {shown.window.to.slice(8, 10)}/{shown.window.to.slice(5, 7)} · {shown.order_basis.label} · Kế hoạch đo: {shown.measurement_plan.label}
        </p>
      </header>

      {detail.stale ? (
        <Notice tone="warn" testId="sd-stale">
          <b>Thông số shop vừa đổi.</b> Thẻ này sẽ được tính lại; số bên dưới là số của lần tính trước.
        </Notice>
      ) : null}
      {detail.status === "draft" ? <Notice tone="info">Nháp: shop chưa thấy thẻ này.</Notice> : null}
      {detail.status === "changes_requested" ? <Notice tone="info">Shop đã yêu cầu chỉnh thẻ này. Đội Juli tính lại và gửi thẻ mới.</Notice> : null}
      {final.note ? <Notice tone="warn">{final.note}</Notice> : null}

      {detail.status === "approved" || detail.status === "executed" ? <ExecutionPanel detail={detail} onExecuted={() => onChanged({ kind: "executed", text: "Đã ghi nhận “Đã làm”. Juli sẽ đọc lại trên Seller Centre để xác minh." })} sheet={final.sheet} /> : null}

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
        </dl>
      </section>

      <section className="sa-card" data-testid="sd-inputs">
        <div className="sa-card__head">
          <h2 className="sa-h2">{isMega ? "Các thay đổi trong chiến dịch" : "Thử “nếu đổi”"}</h2>
          <span className="sa-hint">{adjustable ? "Mỗi lần đổi, mọi con số tính lại." : `Giá trị ${detail.status === "rejected" ? "của thẻ" : "đã duyệt"}: ${viewing || DASH}`}</span>
          {adjustable && edited && !host.readOnly ? <TextChip tone="pink">Giá trị tuỳ chỉnh · ghi vào Lịch sử</TextChip> : null}
          {stale ? (
            <span className="sa-hint" role="status">
              Đang tính lại…
            </span>
          ) : null}
        </div>
        {isMega ? <MegaPanel card={shown} disabled={!adjustable} editable={adjustable && shown.whatif.children_editable !== false} onChange={change} patch={patch} /> : adjustable ? <WhatIfPanel card={shown} disabled={false} onChange={change} patch={patch} /> : null}
        <Checks card={shown} />
        {floorLocked && adjustable ? (
          <div className="sd-lock" data-testid="sd-lock" role="status">
            <span>Phê duyệt đang khoá vì thấp hơn giá sàn vận hành.</span>
            {maxInputs ? (
              <button className="sa-btn sa-btn--s" onClick={() => change({ ...patch, ...maxInputs })} type="button">
                Đặt về mức tối đa {Object.entries(maxInputs).map(([k, v]) => (shown.whatif.sliders.find((x) => x.key === k)?.unit === "pct" ? `${fmt(v, 0)}%` : vnd(v))).join(", ")}
              </button>
            ) : null}
          </div>
        ) : null}
      </section>

      <section className="sa-card" data-testid="sd-numbers-card">
        <NumbersTable card={shown} />
      </section>

      {error ? (
        <p className="sd-error" role="alert">
          {error}
        </p>
      ) : null}

      {sent ? (
        <section className="sd-decision" data-testid="sd-decision">
          <button className="sa-btn sa-btn--primary" disabled={!canDecide || floorLocked || stale || calc === "error" || busy} onClick={() => void approve()} type="button">
            Phê duyệt {edited ? "giá trị tuỳ chỉnh" : "đề xuất của Juli"}
          </button>
          <button className="sa-btn" disabled={!canDecide || busy || stale} onClick={() => setDialog("request")} type="button">
            Yêu cầu chỉnh
          </button>
          <button className="sa-btn" disabled={!canDecide || busy} onClick={() => setDialog("dismiss")} type="button">
            Bỏ qua
          </button>
          <span className="sa-hint" data-testid="sd-approve-hint">
            {floorLocked ? "Không thể phê duyệt: thấp hơn giá sàn vận hành." : "Duyệt xong, Juli đưa bảng thao tác để bạn làm trên Seller Centre."}
          </span>
        </section>
      ) : null}
      {host.readOnly && adjustable ? (
        <p className="sa-hint" title={READ_ONLY_TITLE}>
          {READ_ONLY_TITLE}. Chỉ thử “nếu đổi” được, không ghi lại.
        </p>
      ) : null}

      {host.staff ? <StaffActions detail={detail} onChanged={onChanged} /> : null}

      <DismissDialog busy={busy} error={dialog === "dismiss" ? error : null} onCancel={() => setDialog(null)} onSubmit={(c) => void run("dismissed", "Đã bỏ qua thẻ. Juli không đổi gì trên shop của bạn.", () => host.reco.dismiss(detail.id, c))} open={dialog === "dismiss"} />
      <RequestChangeDialog
        busy={busy}
        error={dialog === "request" ? error : null}
        onCancel={() => setDialog(null)}
        onSubmit={(note) =>
          void run("requested", `Đã gửi yêu cầu chỉnh với các giá trị bạn đang xem${viewing ? ` (${viewing})` : ""}. Đội Juli tính lại và gửi thẻ mới trong 1 ngày làm việc.`, () =>
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
