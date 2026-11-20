"use client";

import { useId, useState } from "react";
import type { JuliCardData, JuliCardVersion, JuliNoCardData } from "@juli/contracts";

import { dirOfChange, dirOfNumber, formatPercent, formatSignedDong } from "../../lib/juli/format";
import { cardHref } from "../../lib/juli/links";
import type { CardState } from "../../lib/juli/use-juli-chat";
import { Directed } from "./delta";

const NOT_ENOUGH = "Chưa đủ dữ liệu";
export const CARD_REFUSED_TEXT = "Juli chưa tạo được thẻ này";

function initialSelection(versions: readonly JuliCardVersion[]): number | null {
  const i = versions.findIndex((v) => v.recommended && v.estimable); // U6d: an unestimable version is never preselected
  return i >= 0 ? i : null;
}

function VersionNumbers({ v }: { readonly v: JuliCardVersion }) {
  if (!v.estimable || v.gmv_p50 === null || v.profit_p50 === null) {
    return <span className="juli-ver__na">{NOT_ENOUGH}</span>;
  }
  const marginDir = dirOfChange(v.margin_before_pct, v.margin_after_pct);
  return (
    <>
      <span className="juli-ver__cell" data-col="gmv">
        <small className="juli-ver__k">ΔGMV {v.days} ngày</small>
        <Directed dir={dirOfNumber(v.gmv_p50)}>{formatSignedDong(v.gmv_p50)}</Directed>
      </span>
      <span className="juli-ver__cell" data-col="profit">
        <small className="juli-ver__k">Δ lợi nhuận</small>
        <Directed dir={dirOfNumber(v.profit_p50)}>{formatSignedDong(v.profit_p50)}</Directed>
      </span>
      <span className="juli-ver__cell juli-num" data-col="cost">
        <small className="juli-ver__k">Chi phí · hoà vốn</small>
        {v.cost_text_vi}
      </span>
      <span className="juli-ver__cell juli-num" data-col="margin">
        <small className="juli-ver__k">Biên</small>
        {v.margin_before_pct !== null && v.margin_after_pct !== null ? (
          <>
            {formatPercent(v.margin_before_pct)} → <Directed dir={marginDir}>{formatPercent(v.margin_after_pct)}</Directed>
          </>
        ) : null}
      </span>
    </>
  );
}

/** U6: the card block rendered by code from the engine's versions. */
export function CardBlock({
  card,
  state,
  readOnly,
  onSend,
  onDismiss,
}: {
  readonly card: JuliCardData;
  readonly state?: CardState;
  readonly readOnly: boolean;
  readonly onSend: (draftRef: string, versionLabel: string) => void;
  readonly onDismiss: (draftRef: string) => void;
}) {
  const [selected, setSelected] = useState<number | null>(() => initialSelection(card.versions));
  const group = useId();
  const phase = state?.phase;

  if (phase === "sent" && state?.code) {
    const label = state.versionLabel ?? (selected !== null ? card.versions[selected]?.label_vi : undefined);
    return <SentLine code={state.code} detail={label ?? card.title_vi} />;
  }
  if (phase === "dismissed") return <div className="juli-none">Đã bỏ qua</div>;
  if (phase === "refused") return <div className="juli-none">{CARD_REFUSED_TEXT}</div>;

  const busy = phase === "sending";
  return (
    <section className="juli-card" aria-label={card.title_vi}>
      <header className="juli-card__head">
        <span className="juli-badge">Nháp</span>
        <h3 className="juli-card__title">{card.title_vi}</h3>
      </header>
      <div className="juli-ver-head" aria-hidden="true">
        <span />
        <span>Phương án</span>
        <span>ΔGMV</span>
        <span>Δ lợi nhuận</span>
        <span>Chi phí · hoà vốn</span>
        <span>Biên</span>
      </div>
      <div className="juli-vers" role="radiogroup" aria-label="Phương án">
        {card.versions.map((v, i) => (
          <label key={v.label_vi} className={`juli-ver${selected === i ? " juli-ver--sel" : ""}${v.estimable ? "" : " juli-ver--na"}`}>
            <input
              type="radio"
              name={group}
              className="juli-ver__radio"
              checked={selected === i}
              disabled={readOnly || busy}
              onChange={() => setSelected(i)}
            />
            <span className="juli-ver__mark" aria-hidden="true" />
            <b className="juli-ver__label">
              {v.label_vi}
              {v.recommended ? <span aria-label="Gợi ý"> ★</span> : null}
            </b>
            <VersionNumbers v={v} />
          </label>
        ))}
      </div>
      <p className="juli-p juli-p--small">{card.recommendation_vi}</p>
      {phase === "failed" ? <p className="juli-p juli-p--small juli-down">Chưa gửi được, thử lại</p> : null}
      {readOnly ? null : (
        <div className="juli-actions">
          <button
            type="button"
            className="juli-btn juli-btn--primary"
            disabled={selected === null || busy}
            onClick={() => selected !== null && onSend(card.draft_ref, card.versions[selected]!.label_vi)}
          >
            Gửi vào Đề xuất
          </button>
          <button type="button" className="juli-btn" disabled={busy} onClick={() => onDismiss(card.draft_ref)}>
            Bỏ qua
          </button>
        </div>
      )}
    </section>
  );
}

export function SentLine({ code, detail }: { readonly code: string; readonly detail: string }) {
  return (
    <div className="juli-sent" role="status">
      <span className="juli-ok" aria-hidden="true">
        ✓
      </span>
      <span className="juli-sent__text">
        <b>Đã gửi</b> · {code} · {detail}
      </span>
      <a href={cardHref(code)}>Xem trong Quyết định</a>
    </div>
  );
}

/** U6e: the no-card line, with the existing card's link on overlap. */
export function NoCardLine({ data }: { readonly data: JuliNoCardData }) {
  return (
    <div className="juli-none">
      {data.reason_vi}
      {data.existing_card_code ? (
        <>
          {" "}
          · <a href={cardHref(data.existing_card_code)}>Xem</a>
        </>
      ) : null}
    </div>
  );
}
