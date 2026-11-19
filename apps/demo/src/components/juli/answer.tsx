"use client";

import type { JuliChoiceOption, JuliTemplate } from "@juli/contracts";

import { reduceAnswer, type AnswerBlockView } from "../../lib/juli/reduce";
import type { CardState, ChatMessage } from "../../lib/juli/use-juli-chat";
import { DataAnswer, NeedsChoice, PathRow, StopLabel, Unsupported, type JuliPlatform } from "./answer-parts";
import { CardBlock, NoCardLine } from "./card-block";

export const ERROR_TEXT = "Juli đang gặp sự cố, thử lại sau";
export const RECONNECTING_TEXT = "Đang kết nối lại…";
export const STOPPED_TEXT = "Đã dừng";

export interface AnswerActions {
  readonly platform: JuliPlatform;
  readonly templates: readonly JuliTemplate[];
  readonly readOnly: boolean;
  readonly cardStates: Readonly<Record<string, CardState>>;
  readonly onSendCard: (draftRef: string, versionLabel: string) => void;
  readonly onDismissCard: (draftRef: string) => void;
  readonly onChoose: (item: string, option: JuliChoiceOption, question: string) => void;
  readonly onOther: () => void;
  readonly onTemplate: (template: JuliTemplate) => void;
  readonly onSwitchPlatform?: (platform: "tiktok" | "shopee") => void;
  readonly onMore: (text: string) => void;
  readonly onRetry: () => void;
  readonly onAskAgain: (messageId: string) => void;
}

function Block({
  block,
  multi,
  interactive,
  actions,
  question,
  savedSentCode,
}: {
  readonly block: AnswerBlockView;
  readonly multi: boolean;
  readonly interactive: boolean;
  readonly actions: AnswerActions;
  readonly question: string;
  readonly savedSentCode?: string;
}) {
  const { platform } = actions;
  return (
    <div className="juli-block">
      {multi && block.title ? <h3 className="juli-block__title">{block.title}</h3> : null}
      {block.label ? <StopLabel label={block.label} /> : null}
      {block.text ? <p className="juli-p juli-p--body">{block.text}</p> : null}
      {block.path && block.path.length > 0 ? <PathRow steps={block.path} platform={platform} /> : null}
      {block.dataAnswers.map((d, i) => (
        <DataAnswer key={`${d.kind}-${i}`} data={d} platform={platform} />
      ))}
      {block.card ? (
        <CardBlock
          card={block.card}
          state={actions.cardStates[block.card.draft_ref] ?? (savedSentCode ? { phase: "sent", code: savedSentCode } : undefined)}
          readOnly={actions.readOnly}
          onSend={actions.onSendCard}
          onDismiss={actions.onDismissCard}
        />
      ) : null}
      {block.noCard ? <NoCardLine data={block.noCard} /> : null}
      {block.needsChoice ? (
        <NeedsChoice
          data={block.needsChoice}
          interactive={interactive}
          templates={actions.templates}
          onChoose={(item, option) => actions.onChoose(item, option, question)}
          onOther={actions.onOther}
          onTemplate={actions.onTemplate}
        />
      ) : null}
      {block.unsupported ? (
        <Unsupported
          data={block.unsupported}
          templates={actions.templates}
          interactive={interactive}
          onTemplate={actions.onTemplate}
          onSwitchPlatform={actions.onSwitchPlatform}
        />
      ) : null}
    </div>
  );
}

/** One seller message + the Juli answer block under it (U3a). */
export function MessagePair({
  message,
  isLast,
  actions,
}: {
  readonly message: ChatMessage;
  readonly isLast: boolean;
  readonly actions: AnswerActions;
}) {
  const view = reduceAnswer(message.events);
  const running = message.status === "running";
  const failed = message.status === "failed" || view.errorCode !== null;
  const saved = message.status === "saved";
  const interactive = isLast && !running;
  const multi = view.blocks.length > 1;
  const thinking = running && !view.restated;

  return (
    <div className="juli-pair" data-status={message.status}>
      <div className="juli-me">{message.question}</div>
      <article className="juli-answer" aria-busy={running} aria-label="Câu trả lời của Juli">
        {saved && message.dataUntilVi ? <span className="juli-label juli-label--saved">{message.dataUntilVi}</span> : null}
        {view.restated ? <p className="juli-p juli-restated">{view.restated}</p> : null}
        {thinking ? <p className="juli-p juli-restated">{view.status?.text_vi ?? "Đang tìm hiểu"}</p> : null}
        {running ? (
          <div className="juli-steps">
            {view.doneSteps.map((s) => (
              <div key={`${s.key}-${s.text_vi}`} className="juli-step">
                <span className="juli-ok" aria-hidden="true">
                  ✓
                </span>
                {s.text_vi}
              </div>
            ))}
            {view.status && view.status.key !== "thinking" ? (
              <div className="juli-status" role="status">
                <span className="juli-spin" aria-hidden="true" />
                {view.status.text_vi}
              </div>
            ) : null}
          </div>
        ) : null}
        {view.blocks.map((block, i) => (
          <Block
            key={i}
            block={block}
            multi={multi}
            interactive={interactive}
            actions={actions}
            question={message.question}
            savedSentCode={saved && i === view.blocks.length - 1 ? message.sentCardCode : undefined}
          />
        ))}
        {view.more.length > 0 ? (
          <div className="juli-opts" role="group" aria-label="Xem tiếp">
            {view.more.map((m) => (
              <button key={m.label_vi} type="button" className="juli-chip" disabled={!interactive} onClick={() => actions.onMore(m.text)}>
                {m.label_vi}
              </button>
            ))}
          </div>
        ) : null}
        {message.reconnecting ? (
          <div className="juli-status" role="status">
            <span className="juli-spin" aria-hidden="true" />
            {RECONNECTING_TEXT}
          </div>
        ) : null}
        {message.status === "stopped" ? <div className="juli-none">{STOPPED_TEXT}</div> : null}
        {failed ? (
          <div className="juli-error" role="alert">
            <p className="juli-p juli-p--body">{ERROR_TEXT}</p>
            {isLast ? (
              <button type="button" className="juli-btn juli-btn--primary" onClick={actions.onRetry}>
                Thử lại
              </button>
            ) : null}
          </div>
        ) : null}
        {saved ? (
          <button type="button" className="juli-btn" onClick={() => actions.onAskAgain(message.id)}>
            Hỏi lại với số liệu mới
          </button>
        ) : null}
      </article>
    </div>
  );
}

