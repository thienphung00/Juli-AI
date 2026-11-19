"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { JuliChoiceOption, JuliTemplate } from "@juli/contracts";

import { formatClock } from "../../lib/juli/format";
import type { JuliClient } from "../../lib/juli/client";
import { useJuliChat } from "../../lib/juli/use-juli-chat";
import { CONNECT_SHOP_HREF } from "../../lib/app-navigation";
import { MessagePair, type AnswerActions } from "./answer";
import type { JuliPlatform } from "./answer-parts";
import { Composer, TemplateRow } from "./composer";
import { HistoryPanel } from "./history";

export interface JuliChatProps {
  readonly client: JuliClient;
  readonly platform: JuliPlatform;
  /** Read-only shop / pending deletion (U11d): Q&A works, the card block has no button. */
  readonly readOnly?: boolean;
  /** U11g: a new shop that is still pulling its data. */
  readonly backfilling?: boolean;
  /** U11b: sync broken for more than 2 days: the last day with data, "dd/mm". */
  readonly staleUntil?: string | null;
  readonly connectHref?: string;
  readonly onSwitchPlatform?: (platform: "tiktok" | "shopee") => void;
  /** Fixed template list (tests); otherwise loaded from `GET /templates`. */
  readonly templates?: readonly JuliTemplate[];
  /** Storage key part so Back restores this shop's conversation (U7a). */
  readonly shopKey?: string;
}

const LIMIT_TEXT = "Bạn đã hỏi nhiều trong giờ này, thử lại sau";
export const BUSY_LIMIT_TEXT = "Juli đang bận, thử lại sau";
export const BACKFILL_TEXT = "Juli đang lấy dữ liệu shop, thử lại sau";

function storageGet(key: string): string | null {
  try {
    return window.sessionStorage.getItem(key);
  } catch {
    return null;
  }
}
function storageSet(key: string, value: string | null) {
  try {
    if (value === null) window.sessionStorage.removeItem(key);
    else window.sessionStorage.setItem(key, value);
  } catch {
    /* storage is a convenience only */
  }
}

export function JuliChat({
  client,
  platform,
  readOnly = false,
  backfilling = false,
  staleUntil = null,
  connectHref = CONNECT_SHOP_HREF,
  onSwitchPlatform,
  templates: fixedTemplates,
  shopKey = "shop",
}: JuliChatProps) {
  const chat = useJuliChat({ client, templates: fixedTemplates, platform });
  const [historyOpen, setHistoryOpen] = useState(false);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const endRef = useRef<HTMLDivElement | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const restoredRef = useRef(false);
  const convKey = `juli_conv_${shopKey}`;
  const scrollKey = `juli_scroll_${shopKey}`;
  const { openConversation, activeConversationId } = chat;

  const limited = chat.limited;
  const inputOff = limited || backfilling;
  const empty = chat.messages.length === 0;

  // U7a: Back returns to the saved conversation at the same scroll.
  useEffect(() => {
    if (restoredRef.current) return;
    restoredRef.current = true;
    const saved = storageGet(convKey);
    if (saved) {
      openConversation(saved)
        .then(() => {
          const top = Number(storageGet(scrollKey));
          if (scrollRef.current && Number.isFinite(top)) scrollRef.current.scrollTop = top;
        })
        .catch(() => storageSet(convKey, null)); // the conversation is gone: start empty
    }
  }, [convKey, scrollKey, openConversation]);

  useEffect(() => {
    storageSet(convKey, activeConversationId);
  }, [convKey, activeConversationId]);

  useEffect(() => {
    if (chat.running) endRef.current?.scrollIntoView({ block: "end" });
  }, [chat.messages, chat.running]);

  const actions = useMemo<AnswerActions>(
    () => ({
      platform,
      templates: chat.templates,
      readOnly: readOnly || chat.readOnlyDetected,
      cardStates: chat.cardStates,
      onSendCard: (ref, label) => void chat.sendCard(ref, label),
      onDismissCard: (ref) => void chat.dismissCard(ref),
      onChoose: (item: string, option: JuliChoiceOption) => void chat.ask({ choice: { item, value: option.value } }, option.label_vi),
      onOther: () => inputRef.current?.focus(),
      onTemplate: (t) => void chat.ask({ template: t.key }, t.label_vi),
      onSwitchPlatform,
      onMore: (text) => void chat.ask({ text }, text),
      onRetry: chat.retry,
      onAskAgain: chat.askAgain,
    }),
    [platform, readOnly, onSwitchPlatform, chat],
  );

  const showTemplates = !chat.running && !inputOff && chat.templates.length > 0;
  const pick = (t: JuliTemplate) => void chat.ask({ template: t.key }, t.label_vi);

  return (
    <div
      className="juli-page"
      data-platform={platform}
      onClickCapture={() => {
        if (scrollRef.current) storageSet(scrollKey, String(scrollRef.current.scrollTop));
      }}
    >
      <div className="juli-toolbar">
        <h1 className="juli-title">Juli</h1>
        <div className="juli-toolbar__spacer" />
        <button type="button" className="juli-btn" aria-expanded={historyOpen} onClick={() => setHistoryOpen((v) => !v)}>
          Lịch sử
        </button>
        <button
          type="button"
          className="juli-btn"
          onClick={() => {
            chat.newConversation();
            setHistoryOpen(false);
          }}
        >
          Cuộc trò chuyện mới
        </button>
      </div>
      <div className="juli-layout">
        {historyOpen ? (
          <HistoryPanel
            items={chat.history}
            activeId={chat.activeConversationId}
            onOpen={(id) => {
              void chat.openConversation(id);
              setHistoryOpen(false);
            }}
            onNew={() => {
              chat.newConversation();
              setHistoryOpen(false);
            }}
            onClose={() => setHistoryOpen(false)}
          />
        ) : null}
        <div className="juli-main">
          <div className="juli-scroll" ref={scrollRef}>
            {empty ? (
              <div className="juli-empty">
                <p className="juli-eyebrow">JULI</p>
                <h2 className="juli-h1">Bạn muốn cải thiện chỉ số nào?</h2>
                {inputOff ? null : (
                  <div className="juli-tiles" role="group" aria-label="Mẫu câu hỏi">
                    {chat.templates.map((t) => (
                      <button key={t.key} type="button" className="juli-tile" onClick={() => pick(t)}>
                        <b>{t.label_vi}</b>
                        <i>7 ngày qua</i>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            ) : (
              <div className="juli-thread">
                {chat.messages.map((m, i) => (
                  <MessagePair key={m.id} message={m} isLast={i === chat.messages.length - 1} actions={actions} />
                ))}
              </div>
            )}
            <div ref={endRef} />
          </div>
          <div className="juli-dock">
            {showTemplates && !empty ? <TemplateRow templates={chat.templates} onPick={pick} /> : null}
            {staleUntil ? (
              <div className="juli-line" data-state="stale">
                <span className="juli-warn" aria-hidden="true" />
                <span className="juli-line__text">Dữ liệu đến {staleUntil}</span>
                <a href={connectHref}>Kết nối dữ liệu</a>
              </div>
            ) : null}
            {limited ? (
              <div className="juli-line" data-state="limit" role="status">
                {chat.limitRetryAt ? `${LIMIT_TEXT} ${formatClock(chat.limitRetryAt)}` : BUSY_LIMIT_TEXT}
              </div>
            ) : null}
            {backfilling ? (
              <div className="juli-line" data-state="backfilling" role="status">
                <span className="juli-spin" aria-hidden="true" />
                {BACKFILL_TEXT}
              </div>
            ) : null}
            <Composer running={chat.running} disabled={inputOff} inputRef={inputRef} onSubmit={(text) => void chat.ask({ text }, text)} onStop={chat.stop} />
          </div>
        </div>
      </div>
    </div>
  );
}
