"use client";

/**
 * The signed-in Quyết định (AC-8.7, ADR-109 d.6, 8–13) — the one module that
 * wires the real clients: decisions + approve, the run ledger poll, each
 * run's SSE stream, confirmations, the P8-C rules / changes / Hoàn tác /
 * questions. Every client is injectable (`clients`) for tests. The anonymous
 * door never imports this module (`replay-module-graph.test.ts`).
 *
 * URL state: `tab=de-xuat|dang-thuc-hien|do-luong`, `run=<id>` (the run shown
 * in Đang thực hiện), `quy-tac=1` (rules editor open).
 */

import type { AgentEvent, DemoDecisionItem, WorkflowRunListItem } from "@juli/contracts";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  deleteShopRule,
  describeRevertError,
  dismissRevertQuestion,
  fetchRevertQuestions,
  fetchRunChanges,
  fetchShopRules,
  putShopRule,
  startRunRevert,
  type AuthedOptions,
} from "../../lib/quyet-dinh/api-client";
import { describeApproveError } from "../../lib/quyet-dinh/approve-errors";
import { approveSequentially } from "../../lib/quyet-dinh/batch";
import { QD_TABS, type QdTabSlug } from "../../lib/quyet-dinh/copy";
import { groupDecisions } from "../../lib/quyet-dinh/grouping";
import type { RevertQuestion, RunChanges, ShopRules } from "../../lib/quyet-dinh/types";
import { approveDemoDecision, fetchRecommendations } from "../../lib/recommendations-api-client";
import { fetchDemoRuns } from "../../lib/run-ledger/api-client";
import { RUN_LEDGER_POLL_INTERVAL_MS } from "../../lib/run-ledger/panel-config";
import { groupRunsIntoLedgerSections } from "../../lib/run-ledger/sections";
import { submitConfirmationDecision } from "../../lib/run-surface/confirmation-client";
import type { ConfirmDecisionFn } from "../../lib/run-surface/confirmation-decision";
import { useRunStream } from "../../lib/run-surface/use-run-stream";
import { AppPageHeader } from "../app-shell/page-header";
import { RunDetailPane, RunQueue, type RevertState } from "./dang-thuc-hien-panel";
import { DeXuatPanel } from "./de-xuat-panel";
import { DoLuongPanel, isExecutedRun, type ChangesState, type QuestionActionState } from "./do-luong-panel";
import { RulesEditor, type RulesEditorProps } from "./rules-editor";

export interface QdClients {
  readonly fetchDecisions: typeof fetchRecommendations;
  readonly approve: typeof approveDemoDecision;
  readonly fetchRuns: typeof fetchDemoRuns;
  readonly fetchRules: typeof fetchShopRules;
  readonly putRule: typeof putShopRule;
  readonly deleteRule: typeof deleteShopRule;
  readonly fetchChanges: typeof fetchRunChanges;
  readonly startRevert: typeof startRunRevert;
  readonly fetchQuestions: typeof fetchRevertQuestions;
  readonly dismissQuestion: typeof dismissRevertQuestion;
  readonly confirm: typeof submitConfirmationDecision;
  /** SSE transport override (tests); the real one is same-origin `fetch`. */
  readonly streamFetch?: typeof fetch;
}

export const REAL_QD_CLIENTS: QdClients = {
  fetchDecisions: fetchRecommendations,
  approve: approveDemoDecision,
  fetchRuns: fetchDemoRuns,
  fetchRules: fetchShopRules,
  putRule: putShopRule,
  deleteRule: deleteShopRule,
  fetchChanges: fetchRunChanges,
  startRevert: startRunRevert,
  fetchQuestions: fetchRevertQuestions,
  dismissQuestion: dismissRevertQuestion,
  confirm: submitConfirmationDecision,
};

type Load<T> = { status: "loading" } | { status: "error" } | { status: "ready"; data: T };

export interface QdQuery {
  readonly tab: QdTabSlug;
  readonly run: string | null;
  readonly rulesOpen: boolean;
}

export function qdHref(query: QdQuery): string {
  const params = new URLSearchParams();
  params.set("tab", query.tab);
  if (query.run) params.set("run", query.run);
  if (query.rulesOpen) params.set("quy-tac", "1");
  return `/decisions?${params.toString()}`;
}

const TITLES: Readonly<Record<QdTabSlug, string>> = {
  "de-xuat": "Chưa có đề xuất mới",
  "dang-thuc-hien": "Juli tự áp dụng lên TikTok Shop",
  "do-luong": "Đo kết quả sau 7 và 14 ngày",
};

function useNow(intervalMs = 1000): number | null {
  const [now, setNow] = useState<number | null>(null);
  useEffect(() => {
    const tick = () => setNow(Date.now());
    const first = window.setTimeout(tick, 0);
    const timer = window.setInterval(tick, intervalMs);
    return () => {
      window.clearTimeout(first);
      window.clearInterval(timer);
    };
  }, [intervalMs]);
  return now;
}

export function SignedInQuyetDinh({
  token,
  shop,
  query,
  onNavigate,
  clients = REAL_QD_CLIENTS,
}: {
  readonly token: string;
  readonly shop: { readonly id: string; readonly name: string } | null;
  readonly query: QdQuery;
  readonly onNavigate: (href: string) => void;
  readonly clients?: QdClients;
}) {
  if (!shop) {
    return (
      <section aria-labelledby="qd-title" className="qd-page">
        <AppPageHeader eyebrow="Quyết định" title="Việc cần bạn quyết định" titleId="qd-title" />
        <div className="card qd-empty" role="status">
          <p>Bạn chưa chọn shop đang thao tác. Mở Kết nối TikTok Shop để chọn shop.</p>
          <Link className="btn-secondary" href="/auth/connect-shop">
            Kết nối TikTok Shop
          </Link>
        </div>
      </section>
    );
  }
  return <QuyetDinhForShop clients={clients} onNavigate={onNavigate} query={query} shop={shop} token={token} />;
}

function QuyetDinhForShop({
  token,
  shop,
  query,
  onNavigate,
  clients,
}: {
  readonly token: string;
  readonly shop: { readonly id: string; readonly name: string };
  readonly query: QdQuery;
  readonly onNavigate: (href: string) => void;
  readonly clients: QdClients;
}) {
  const auth: AuthedOptions = useMemo(() => ({ token, shopId: shop.id }), [token, shop.id]);
  const nowMs = useNow();

  // -- reads ------------------------------------------------------------------
  const [decisions, setDecisions] = useState<Load<readonly DemoDecisionItem[]>>({ status: "loading" });
  const [decisionsKey, setDecisionsKey] = useState(0);
  useEffect(() => {
    let cancelled = false;
    clients
      .fetchDecisions({ token, shopId: shop.id })
      .then((items) => !cancelled && setDecisions({ status: "ready", data: items }))
      .catch(() => !cancelled && setDecisions({ status: "error" }));
    return () => {
      cancelled = true;
    };
  }, [clients, token, shop.id, decisionsKey]);

  const [rules, setRules] = useState<Load<ShopRules>>({ status: "loading" });
  const loadRules = useCallback(
    () =>
      clients
        .fetchRules(auth)
        .then((data) => setRules({ status: "ready", data }))
        .catch(() => setRules({ status: "error" })),
    [clients, auth],
  );
  useEffect(() => {
    void loadRules();
  }, [loadRules]);

  const [runs, setRuns] = useState<Load<readonly WorkflowRunListItem[]>>({ status: "loading" });
  const [runsKey, setRunsKey] = useState(0);
  const polling = query.tab !== "de-xuat";
  useEffect(() => {
    let cancelled = false;
    const load = () =>
      clients
        .fetchRuns({ token, shopId: shop.id })
        .then((data) => !cancelled && setRuns({ status: "ready", data }))
        .catch(() => !cancelled && setRuns((previous) => (previous.status === "ready" ? previous : { status: "error" })));
    void load();
    const timer = polling ? window.setInterval(load, RUN_LEDGER_POLL_INTERVAL_MS) : null;
    return () => {
      cancelled = true;
      if (timer !== null) window.clearInterval(timer);
    };
  }, [clients, token, shop.id, polling, runsKey]);

  const [questions, setQuestions] = useState<readonly RevertQuestion[]>([]);
  useEffect(() => {
    if (query.tab !== "do-luong") return;
    let cancelled = false;
    clients
      .fetchQuestions(auth)
      .then((data) => !cancelled && setQuestions(data))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [clients, auth, query.tab]);

  const [changesByRun, setChangesByRun] = useState<Record<string, ChangesState>>({});
  const requestedChanges = useRef(new Set<string>());
  const runList = useMemo(() => (runs.status === "ready" ? runs.data : []), [runs]);
  useEffect(() => {
    if (query.tab !== "do-luong") return;
    for (const run of runList.filter(isExecutedRun)) {
      if (requestedChanges.current.has(run.id)) continue;
      requestedChanges.current.add(run.id);
      clients
        .fetchChanges(auth, run.id)
        .then((changes) => setChangesByRun((map) => ({ ...map, [run.id]: { status: "ready", changes } })))
        .catch(() => setChangesByRun((map) => ({ ...map, [run.id]: { status: "error" } })));
    }
  }, [clients, auth, query.tab, runList]);

  // -- Đề xuất actions ---------------------------------------------------------
  const [approvedIds, setApprovedIds] = useState<ReadonlySet<string>>(() => new Set());
  const [droppedIds, setDroppedIds] = useState<ReadonlySet<string>>(() => new Set());
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState<string | null>(null);
  const [approveErrors, setApproveErrors] = useState<string[]>([]);

  const navigate = useCallback((next: Partial<QdQuery>) => onNavigate(qdHref({ ...query, ...next })), [onNavigate, query]);

  const handleApprove = useCallback(
    (cardIds: readonly string[]) => {
      if (busy || cardIds.length === 0) return;
      setBusy(true);
      setApproveErrors([]);
      setProgress(`Đang duyệt 0/${cardIds.length} thẻ…`);
      void approveSequentially(
        cardIds,
        (cardId) => clients.approve(cardId, { token, shopId: shop.id }),
        (done, total) => setProgress(`Đang duyệt ${done}/${total} thẻ…`),
      ).then((results) => {
        setBusy(false);
        setProgress(null);
        const ok = results.filter((result) => result.runId !== null);
        setApprovedIds((ids) => new Set([...ids, ...ok.map((result) => result.cardId)]));
        setApproveErrors(results.filter((result) => result.runId === null).map((result) => describeApproveError(result.error)));
        if (ok.length > 0) {
          setRunsKey((key) => key + 1);
          navigate({ tab: "dang-thuc-hien", run: ok[0].runId, rulesOpen: false });
        }
      });
    },
    [busy, clients, token, shop.id, navigate],
  );

  // -- rules editor ------------------------------------------------------------
  const onSaveRule = useCallback(
    async (...[ruleKey, value, setBy, scopeRef]: Parameters<RulesEditorProps["onSave"]>) => {
      await clients.putRule(auth, ruleKey, value, setBy, scopeRef);
      await loadRules();
    },
    [clients, auth, loadRules],
  );
  const onDeleteRule = useCallback(
    async (...[ruleKey, scopeRef]: Parameters<RulesEditorProps["onDelete"]>) => {
      await clients.deleteRule(auth, ruleKey, scopeRef);
      await loadRules();
    },
    [clients, auth, loadRules],
  );

  // -- Đo lường actions --------------------------------------------------------
  const [questionStates, setQuestionStates] = useState<Record<string, QuestionActionState>>({});
  const onRevertQuestion = (question: RevertQuestion) => {
    setQuestionStates((map) => ({ ...map, [question.id]: { busy: true, message: null } }));
    clients
      .startRevert(auth, question.run_id)
      .then(({ runId }) => {
        setRunsKey((key) => key + 1);
        navigate({ tab: "dang-thuc-hien", run: runId });
      })
      .catch((error: unknown) =>
        setQuestionStates((map) => ({ ...map, [question.id]: { busy: false, message: describeRevertError(error) } })),
      );
  };
  const onDismissQuestion = (question: RevertQuestion) => {
    setQuestionStates((map) => ({ ...map, [question.id]: { busy: true, message: null } }));
    clients
      .dismissQuestion(auth, question.id)
      .then(() => setQuestions((list) => list.filter((item) => item.id !== question.id)))
      .catch(() =>
        setQuestionStates((map) => ({
          ...map,
          [question.id]: { busy: false, message: "Chưa lưu được lựa chọn. Vui lòng thử lại." },
        })),
      );
  };

  // -- selected run --------------------------------------------------------------
  const sections = groupRunsIntoLedgerSections(runList);
  const defaultRun = sections.waitingOnYou[0] ?? sections.running[0] ?? sections.finished[0] ?? null;
  const selectedRun = runList.find((run) => run.id === query.run) ?? (query.run ? null : defaultRun);

  const groups = useMemo(() => (decisions.status === "ready" ? groupDecisions(decisions.data) : []), [decisions]);
  const title =
    query.tab === "de-xuat" && groups.length > 0 ? groups[0].title : TITLES[query.tab];
  const eyebrow = `Quyết định · ${QD_TABS.find((tab) => tab.slug === query.tab)!.label}`;

  return (
    <section aria-labelledby="qd-title" className="qd-page">
      <AppPageHeader
        eyebrow={eyebrow}
        lede={
          <>
            Bạn đang thao tác trên: <strong>{shop.name}</strong>
          </>
        }
        title={title}
        titleId="qd-title"
      />

      <div aria-label="Quyết định" className="pt-tabs" role="tablist">
        {QD_TABS.map((tab) => (
          <button
            aria-selected={query.tab === tab.slug}
            className="pt-tabs__tab"
            key={tab.slug}
            onClick={() => navigate({ tab: tab.slug, run: tab.slug === "dang-thuc-hien" ? query.run : null })}
            role="tab"
            type="button"
          >
            {tab.label}
          </button>
        ))}
      </div>

      {query.rulesOpen ? (
        rules.status === "ready" ? (
          <RulesEditor
            onClose={() => navigate({ rulesOpen: false })}
            onDelete={onDeleteRule}
            onSave={onSaveRule}
            rules={rules.data}
          />
        ) : (
          <p className="qd-muted" role="status">
            {rules.status === "loading" ? "Đang tải quy tắc…" : "Không tải được quy tắc của shop."}
          </p>
        )
      ) : null}

      {approveErrors.length > 0 ? (
        <div className="qd-error-box" role="alert">
          <p>Không duyệt được {approveErrors.length} thẻ:</p>
          <ul>
            {[...new Set(approveErrors)].map((message) => (
              <li key={message}>{message}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {query.tab === "de-xuat" ? (
        decisions.status === "loading" ? (
          <p role="status">Đang tải đề xuất cho shop của bạn…</p>
        ) : decisions.status === "error" ? (
          <div className="card qd-empty" role="alert">
            <p>Không thể tải đề xuất cho shop của bạn. Vui lòng thử lại.</p>
            <button
              className="btn-secondary"
              onClick={() => {
                setDecisions({ status: "loading" });
                setDecisionsKey((key) => key + 1);
              }}
              type="button"
            >
              Thử lại
            </button>
          </div>
        ) : groups.length === 0 ? (
          <div className="card qd-empty" role="status">
            <p>Juli đang thu thập dữ liệu shop của bạn. Đề xuất đầu tiên sẽ xuất hiện trong vòng 24 giờ.</p>
          </div>
        ) : (
          <DeXuatPanel
            approvedIds={approvedIds}
            busy={busy}
            droppedIds={droppedIds}
            groups={groups}
            onApprove={handleApprove}
            onDrop={(cardId) => setDroppedIds((ids) => new Set(ids).add(cardId))}
            onOpenRules={() => navigate({ rulesOpen: true })}
            progress={progress}
            rules={rules.status === "ready" ? rules.data : null}
            rulesStatus={rules.status}
          />
        )
      ) : null}

      {query.tab === "dang-thuc-hien" ? (
        <div className="qd-dt">
          <div className="qd-dt__main">
            {runs.status === "loading" ? (
              <p role="status">Đang tải danh sách…</p>
            ) : runs.status === "error" ? (
              <p className="qd-error" role="alert">
                Không thể tải danh sách luồng thực hiện.
              </p>
            ) : selectedRun ? (
              <SelectedRun
                auth={auth}
                clients={clients}
                key={selectedRun.id}
                nowMs={nowMs}
                onRevertStarted={(runId) => {
                  setRunsKey((key) => key + 1);
                  navigate({ tab: "dang-thuc-hien", run: runId });
                }}
                run={selectedRun}
              />
            ) : query.run ? (
              <p className="qd-muted" role="status">
                Đang tìm lượt chạy này…
              </p>
            ) : (
              <div className="card qd-empty" role="status">
                <p>Chưa có quyết định nào đang thực hiện. Duyệt thẻ ở tab Đề xuất để Juli bắt đầu.</p>
              </div>
            )}
          </div>
          <RunQueue onSelect={(runId) => navigate({ run: runId })} runs={runList} selectedId={selectedRun?.id ?? null} />
        </div>
      ) : null}

      {query.tab === "do-luong" ? (
        <DoLuongPanel
          changesByRun={changesByRun}
          nowMs={nowMs}
          onDismissQuestion={onDismissQuestion}
          onOpenRun={(runId) => navigate({ tab: "dang-thuc-hien", run: runId })}
          onRevertQuestion={onRevertQuestion}
          questionStates={questionStates}
          questions={questions}
          runs={runList}
        />
      ) : null}
    </section>
  );
}

function isTerminal(events: readonly AgentEvent[]): boolean {
  return events.some((event) => event.event_type === "workflow.completed" || event.event_type === "workflow.failed");
}

function SelectedRun({
  run,
  auth,
  clients,
  nowMs,
  onRevertStarted,
}: {
  readonly run: WorkflowRunListItem;
  readonly auth: AuthedOptions;
  readonly clients: QdClients;
  readonly nowMs: number | null;
  readonly onRevertStarted: (runId: string) => void;
}) {
  const { events, streamStatus } = useRunStream(run.id, {
    token: auth.token,
    shopId: auth.shopId,
    fetchImpl: clients.streamFetch,
  });
  const terminal = isTerminal(events);
  const [changes, setChanges] = useState<RunChanges | null>(null);
  useEffect(() => {
    let cancelled = false;
    clients
      .fetchChanges(auth, run.id)
      .then((data) => !cancelled && setChanges(data))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [clients, auth, run.id, terminal]);

  const [revertState, setRevertState] = useState<RevertState>({ status: "idle" });
  const confirm: ConfirmDecisionFn = (runId, toolCallId, decision, optionId, options = {}) =>
    clients.confirm(runId, toolCallId, decision, optionId, { ...options, shopId: auth.shopId });

  return (
    <RunDetailPane
      changes={changes}
      confirm={confirm}
      events={events}
      isRevert={Boolean(changes?.reverts_run_id)}
      nowMs={nowMs}
      onRevert={() => {
        setRevertState({ status: "submitting" });
        clients
          .startRevert(auth, run.id)
          .then(({ runId }) => {
            setRevertState({ status: "idle" });
            onRevertStarted(runId);
          })
          .catch((error: unknown) => setRevertState({ status: "error", message: describeRevertError(error) }));
      }}
      reconnecting={streamStatus === "reconnecting"}
      revertState={revertState}
      run={run}
      token={auth.token}
    />
  );
}
