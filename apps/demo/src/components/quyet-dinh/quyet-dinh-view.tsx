"use client";

/**
 * Quyết định's P10 screens (AC-10.3, ADR-109 Amendment 1) behind an
 * injected data source: Đề xuất (card collapsed / Xem thêm / approve /
 * reject), Đang thực hiện (run timeline, consent with edits, photo, Seller
 * Center checklist, Hoàn tác) and Đo lường. Two doors render it:
 *
 * - `SignedInQuyetDinh` with the real backend clients;
 * - `SampleQuyetDinh` (signed out, "Bản minh họa") with in-memory fixture
 *   clients — every approve / reject / confirm only changes local state.
 *
 * This module (and everything it imports) holds no fetch call site and no
 * backend route literal: the signed-out door reaches it (ADR-094 d.1,
 * `replay-module-graph.test.ts`). The real clients are wired in
 * `signed-in-quyet-dinh.tsx` only.
 *
 * URL state: `tab=de-xuat|dang-thuc-hien|do-luong`, `run=<id>` (the run shown
 * in Đang thực hiện), `moc=ngay-0|ngay-7|ngay-14` (Đo lường tab), `quy-tac=1`
 * (rules editor open).
 */

import type { DemoDecisionItem } from "@juli/contracts";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { describeApproveError } from "../../lib/quyet-dinh/approve-errors";
import { approveSequentially } from "../../lib/quyet-dinh/batch";
import { cardView, type CardView } from "../../lib/quyet-dinh/card-model";
import {
  QdApiError,
  describeRevertError,
  isExternalChange,
  photoChecksOf,
  type AuthedOptions,
  type QdClients,
} from "../../lib/quyet-dinh/client-types";
import { QD_TABS, type QdTabSlug } from "../../lib/quyet-dinh/copy";
import { groupDecisions } from "../../lib/quyet-dinh/grouping";
import { MEASURE_TABS, type MeasureTab } from "../../lib/quyet-dinh/measure-model";
import type { CardStatus, P10DecisionItem, PhotoCheck, QdRun, RunDetail, SellerInstructions } from "../../lib/quyet-dinh/p10-types";
import { REVERT_REASONS, type ReasonChoice } from "../../lib/quyet-dinh/reasons";
import { runChip, runKind, runPhase, type Chip } from "../../lib/quyet-dinh/run-model";
import { buildRunTimeline, type RunKind } from "../../lib/quyet-dinh/timeline";
import type { RevertQuestion, RunChanges, ShopRules } from "../../lib/quyet-dinh/types";
import { RUN_LEDGER_POLL_INTERVAL_MS } from "../../lib/run-ledger/panel-config";
import { groupRunsIntoLedgerSections } from "../../lib/run-ledger/sections";
import { AppPageHeader } from "../app-shell/page-header";
import { RunQueue } from "./dang-thuc-hien-panel";
import { DeXuatPanel } from "./de-xuat-panel";
import {
  DoLuongPanel,
  IDLE_REVERT,
  defaultTab,
  isExecutedRun,
  measureTitle,
  type ChangesState,
  type MeasureItem,
  type MeasurementState,
  type RevertActionState,
} from "./do-luong-panel";
import { VideoAnalysis } from "../content-analysis/video-analysis";
import { ContentRunPanel, contentChip, contentPhase } from "./content-run-panel";
import { RulesEditor, type RulesEditorProps } from "./rules-editor";
import { RunPanel, type LoadState, type PhotoState } from "./run-panel";

export type { QdClients } from "../../lib/quyet-dinh/client-types";

type Load<T> = { status: "loading" } | { status: "error" } | { status: "ready"; data: T };

export interface QdQuery {
  readonly tab: QdTabSlug;
  readonly run: string | null;
  readonly rulesOpen: boolean;
  /** Đo lường's tab (`moc`), or null for the default. */
  readonly measureTab?: MeasureTab | null;
  /** `the=<card id>`: Đề xuất scrolls to that card and outlines it for 3 s (Phân tích's "Xem đề xuất ›"). */
  readonly focusCard?: string | null;
  /** `nhom=ctr|ctor|aov`: the same for that metric's card group ("Xem N đề xuất ›"). */
  readonly focusMetric?: string | null;
}

export function resolveMeasureTab(value: string | null | undefined): MeasureTab | null {
  return MEASURE_TABS.find((entry) => entry.slug === value)?.id ?? null;
}

export function qdHref(query: QdQuery): string {
  const params = new URLSearchParams();
  params.set("tab", query.tab);
  if (query.run) params.set("run", query.run);
  if (query.tab === "do-luong" && query.measureTab) {
    params.set("moc", MEASURE_TABS.find((entry) => entry.id === query.measureTab)!.slug);
  }
  if (query.rulesOpen) params.set("quy-tac", "1");
  return `/decisions?${params.toString()}`;
}

const RUN_HEADER: Readonly<Record<RunKind, { eyebrow: string; title: string }>> = {
  listing: { eyebrow: "Quyết định · Đang thực hiện", title: "Juli tự áp dụng lên TikTok Shop" },
  photo: { eyebrow: "Quyết định · Đang thực hiện · Ảnh bìa", title: "Juli tải ảnh của bạn lên TikTok Shop" },
  manual: { eyebrow: "Quyết định · Đang thực hiện · Khuyến mãi", title: "Bạn áp dụng trên Seller Center, Juli theo dõi" },
  revert: { eyebrow: "Quyết định · Đang thực hiện · Hoàn tác", title: "Khôi phục nội dung cũ" },
  content: { eyebrow: "Quyết định · Đang thực hiện", title: "Juli soạn kịch bản, bạn quay hoặc LIVE" },
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

function reasonLabel(code: string): string {
  return REVERT_REASONS.find((reason) => reason.code === code)?.label ?? code;
}

function errorSentence(error: unknown, fallback: string): string {
  if (error instanceof QdApiError) {
    if (error.serverMessage && error.status < 500) return error.serverMessage;
    if (error.status === 401) return "Phiên đăng nhập của bạn không còn hiệu lực. Vui lòng đăng nhập lại.";
  }
  return fallback;
}

export function QuyetDinhView({
  token,
  shop,
  query,
  onNavigate,
  clients,
  sample = false,
}: {
  readonly token: string;
  readonly shop: { readonly id: string; readonly name: string };
  readonly query: QdQuery;
  readonly onNavigate: (href: string) => void;
  readonly clients: QdClients;
  /** The signed-out "Bản minh họa": shows the sample notice. */
  readonly sample?: boolean;
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

  const [runs, setRuns] = useState<Load<readonly QdRun[]>>({ status: "loading" });
  const [runsKey, setRunsKey] = useState(0);
  const polling = query.tab !== "de-xuat";
  useEffect(() => {
    let cancelled = false;
    const load = () =>
      clients
        .fetchRuns({ token, shopId: shop.id })
        .then((data) => !cancelled && setRuns({ status: "ready", data: data as QdRun[] }))
        .catch(() => !cancelled && setRuns((previous) => (previous.status === "ready" ? previous : { status: "error" })));
    void load();
    const timer = polling ? window.setInterval(load, RUN_LEDGER_POLL_INTERVAL_MS) : null;
    return () => {
      cancelled = true;
      if (timer !== null) window.clearInterval(timer);
    };
  }, [clients, token, shop.id, polling, runsKey]);
  const refreshRuns = useCallback(() => setRunsKey((key) => key + 1), []);

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

  const runList = useMemo(() => (runs.status === "ready" ? runs.data : []), [runs]);

  // Changes + measurement for the executed runs (Đo lường).
  const [changesByRun, setChangesByRun] = useState<Record<string, ChangesState>>({});
  const [measureByRun, setMeasureByRun] = useState<Record<string, MeasurementState>>({});
  const requested = useRef(new Set<string>());
  useEffect(() => {
    if (query.tab !== "do-luong") return;
    for (const run of runList.filter(isExecutedRun)) {
      if (requested.current.has(run.id)) continue;
      requested.current.add(run.id);
      clients
        .fetchChanges(auth, run.id)
        .then((changes) => setChangesByRun((map) => ({ ...map, [run.id]: { status: "ready", changes } })))
        .catch(() => setChangesByRun((map) => ({ ...map, [run.id]: { status: "error" } })));
      clients
        .fetchMeasurement(auth, run.id)
        .then((measurement) => setMeasureByRun((map) => ({ ...map, [run.id]: { status: "ready", measurement } })))
        .catch(() => setMeasureByRun((map) => ({ ...map, [run.id]: { status: "ready", measurement: null } })));
    }
  }, [clients, auth, query.tab, runList]);

  // -- cards ---------------------------------------------------------------------
  const items = useMemo(() => (decisions.status === "ready" ? (decisions.data as P10DecisionItem[]) : []), [decisions]);
  const views = useMemo(() => new Map(items.map((item) => [item.id, cardView(item)])), [items]);
  const [statusOverrides, setStatusOverrides] = useState<Record<string, CardStatus>>({});
  const [runByCard, setRunByCard] = useState<Record<string, string>>({});
  const [cardErrors, setCardErrors] = useState<Record<string, string>>({});
  const cardFor = useCallback(
    (run: Pick<QdRun, "id" | "product_name" | "decision_id">): CardView | null => {
      if (run.decision_id && views.has(run.decision_id)) return views.get(run.decision_id)!;
      const byRun = Object.entries(runByCard).find(([, runId]) => runId === run.id)?.[0];
      if (byRun && views.has(byRun)) return views.get(byRun)!;
      for (const view of views.values()) if (view.title === run.product_name) return view;
      return null;
    },
    [runByCard, views],
  );

  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState<string | null>(null);
  const [approveErrors, setApproveErrors] = useState<string[]>([]);

  const navigate = useCallback((next: Partial<QdQuery>) => onNavigate(qdHref({ ...query, ...next })), [onNavigate, query]);

  const handleApprove = useCallback(
    (cardIds: readonly string[]) => {
      if (busy || cardIds.length === 0) return;
      const batch = cardIds.length > 1;
      setBusy(true);
      setApproveErrors([]);
      setCardErrors((map) => {
        const next = { ...map };
        for (const id of cardIds) delete next[id];
        return next;
      });
      setProgress(batch ? `Đang duyệt 0/${cardIds.length} thẻ…` : null);
      void approveSequentially(
        cardIds,
        (cardId) => clients.approve(cardId, { token, shopId: shop.id }),
        (done, total) => batch && setProgress(`Đang duyệt ${done}/${total} thẻ…`),
      ).then((results) => {
        setBusy(false);
        setProgress(null);
        const ok = results.filter((result) => result.runId !== null);
        setStatusOverrides((map) => ({ ...map, ...Object.fromEntries(ok.map((result) => [result.cardId, "running" as const])) }));
        setRunByCard((map) => ({ ...map, ...Object.fromEntries(ok.map((result) => [result.cardId, result.runId!])) }));
        const failed = results.filter((result) => result.runId === null);
        if (batch) setApproveErrors(failed.map((result) => describeApproveError(result.error)));
        else
          setCardErrors((map) => ({
            ...map,
            ...Object.fromEntries(failed.map((result) => [result.cardId, describeApproveError(result.error)])),
          }));
        if (ok.length > 0) {
          refreshRuns();
          if (batch) navigate({ tab: "dang-thuc-hien", run: ok[0].runId, rulesOpen: false });
        }
      });
    },
    [busy, clients, token, shop.id, navigate, refreshRuns],
  );

  const handleReject = useCallback(
    async (cardId: string, choice: ReasonChoice) => {
      try {
        await clients.reject(auth, cardId, choice);
      } catch (error) {
        throw new Error(errorSentence(error, "Chưa từ chối được thẻ này. Vui lòng thử lại."));
      }
      setStatusOverrides((map) => ({ ...map, [cardId]: "rejected" }));
    },
    [clients, auth],
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

  // -- Hoàn tác (Đang thực hiện and Đo lường) -------------------------------------------
  const [revertMeta, setRevertMeta] = useState<Record<string, { reason: string; startedAt: string }>>({});
  const [measureActions, setMeasureActions] = useState<Record<string, RevertActionState>>({});
  const setAction = (runId: string, patch: Partial<RevertActionState>) =>
    setMeasureActions((map) => ({ ...map, [runId]: { ...(map[runId] ?? IDLE_REVERT), ...patch } }));

  const startRevert = useCallback(
    async (runId: string, choice: ReasonChoice): Promise<{ runId: string } | { conflict: string } | { error: string }> => {
      try {
        const result = await clients.startRevert(auth, runId, choice);
        setRevertMeta((map) => ({
          ...map,
          [result.runId]: { reason: reasonLabel(choice.reason_code), startedAt: new Date().toISOString() },
        }));
        refreshRuns();
        return result;
      } catch (error) {
        if (isExternalChange(error)) return { conflict: (error as QdApiError).serverMessage ?? describeRevertError(error) };
        return { error: describeRevertError(error) };
      }
    },
    [clients, auth, refreshRuns],
  );

  const onMeasureRevert = (item: MeasureItem, choice: ReasonChoice) => {
    setAction(item.run.id, { busy: true, error: null, conflict: null });
    void startRevert(item.run.id, choice).then((result) => {
      if ("runId" in result) setAction(item.run.id, { busy: false, revertRunId: result.runId });
      else if ("conflict" in result) setAction(item.run.id, { busy: false, conflict: result.conflict });
      else setAction(item.run.id, { busy: false, error: result.error });
    });
  };

  const onMeasureKeep = (item: MeasureItem) => {
    const questionId =
      (item.measurement?.status === "ready" ? item.measurement.measurement?.day7?.question_id : null) ?? item.question?.id ?? null;
    if (!questionId) {
      setAction(item.run.id, { kept: true });
      return;
    }
    setAction(item.run.id, { busy: true, error: null });
    clients
      .dismissQuestion(auth, questionId)
      .then(() => setAction(item.run.id, { busy: false, kept: true }))
      .catch(() => setAction(item.run.id, { busy: false, error: "Chưa lưu được lựa chọn. Vui lòng thử lại." }));
  };

  // -- selected run --------------------------------------------------------------
  const sections = groupRunsIntoLedgerSections(runList);
  const defaultRun = sections.waitingOnYou[0] ?? sections.running[0] ?? sections.finished[0] ?? null;
  const selectedRun = runList.find((run) => run.id === query.run) ?? (query.run ? null : (defaultRun as QdRun | null));
  const [selectedState, setSelectedState] = useState<{ runId: string; kind: RunKind; chip: Chip; headline?: string | null } | null>(
    null,
  );
  const selectedKind = selectedState && selectedRun && selectedState.runId === selectedRun.id ? selectedState.kind : "listing";

  // -- measure items -------------------------------------------------------------
  const measureItems: MeasureItem[] = useMemo(
    () =>
      runList
        .filter(isExecutedRun)
        .filter((run) => {
          const state = changesByRun[run.id];
          if (state?.status !== "ready") return true;
          if (state.changes.reverts_run_id !== null) return false;
          const m = measureByRun[run.id];
          const measured = m?.status === "ready" && m.measurement !== null;
          const executor = cardFor(run)?.executor;
          return state.changes.changes.length > 0 || measured || executor === "seller_center" || executor === "juli_drafts";
        })
        .map((run) => ({
          run,
          card: cardFor(run),
          changes: changesByRun[run.id],
          measurement: measureByRun[run.id],
          question: questions.find((question) => question.run_id === run.id && !question.revert_run_id) ?? null,
          action: measureActions[run.id] ?? IDLE_REVERT,
        })),
    [runList, changesByRun, measureByRun, questions, measureActions, cardFor],
  );
  const measureTab = query.measureTab ?? defaultTab(measureItems);

  // -- header ----------------------------------------------------------------------
  const groups = useMemo(() => (decisions.status === "ready" ? groupDecisions(decisions.data) : []), [decisions]);
  let eyebrow = `Quyết định · ${QD_TABS.find((tab) => tab.slug === query.tab)!.label}`;
  let title = "Chưa có đề xuất mới";
  if (query.tab === "de-xuat" && groups.length > 0) title = groups[0].title;
  if (query.tab === "dang-thuc-hien") ({ eyebrow, title } = RUN_HEADER[selectedKind]);
  if (query.tab === "dang-thuc-hien" && selectedKind === "content" && selectedState?.headline) title = selectedState.headline;
  if (query.tab === "do-luong") title = measureItems.length > 0 ? measureTitle(measureItems, measureTab) : "Đo kết quả sau 7 và 14 ngày";

  const runHref = (runId: string | null) => qdHref({ tab: "dang-thuc-hien", run: runId, rulesOpen: false });

  return (
    <section aria-labelledby="qd-title" className="qd-page">
      <AppPageHeader eyebrow={eyebrow} title={title} titleId="qd-title" />
      {sample ? (
        <p className="demo-notice sample-notice" data-testid="mock-data-notice">
          Dữ liệu mẫu · {shop.name} là shop minh họa. Duyệt, từ chối hay xác nhận ở đây chỉ đổi trên trang này, không ghi gì lên TikTok Shop.
        </p>
      ) : null}

      <div aria-label="Quyết định" className="qv-tabs" role="tablist">
        {QD_TABS.map((tab) => (
          <button
            aria-selected={query.tab === tab.slug}
            className="qv-tab"
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
            offApiReadOnly={sample}
            onClose={() => navigate({ rulesOpen: false })}
            onDelete={onDeleteRule}
            onSave={onSaveRule}
            rules={rules.data}
          />
        ) : (
          <p className="qv-status-line" role="status">
            {rules.status === "loading" ? "Đang tải quy tắc…" : "Không tải được quy tắc của shop."}
          </p>
        )
      ) : null}

      {approveErrors.length > 0 ? (
        <div className="qv-orange" role="alert">
          <div className="qv-orange__title">Không duyệt được {approveErrors.length} thẻ:</div>
          <ul>
            {[...new Set(approveErrors)].map((message) => (
              <li key={message}>{message}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {query.tab === "de-xuat" ? (
        decisions.status === "loading" ? (
          <p className="qv-status-line" role="status">
            Đang tải đề xuất cho shop của bạn…
          </p>
        ) : decisions.status === "error" ? (
          <div className="qv-empty" role="alert">
            <p>Không thể tải đề xuất cho shop của bạn. Vui lòng thử lại.</p>
            <button
              className="qv-btn qv-btn--secondary"
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
          <div className="qv-empty" role="status">
            <p>Juli đang thu thập dữ liệu shop của bạn. Đề xuất đầu tiên sẽ xuất hiện trong vòng 24 giờ.</p>
          </div>
        ) : (
          <DeXuatPanel
            busy={busy}
            cardErrors={cardErrors}
            focusCard={query.focusCard ?? null}
            focusMetric={query.focusMetric ?? null}
            groups={groups}
            onApprove={handleApprove}
            onOpenRules={() => navigate({ rulesOpen: true })}
            onOpenRun={(runId) => navigate({ tab: "dang-thuc-hien", run: runId, rulesOpen: false })}
            onReject={handleReject}
            progress={progress}
            progressHref={runHref}
            rules={rules.status === "ready" ? rules.data : null}
            rulesStatus={rules.status}
            runByCard={runByCard}
            statusOverrides={statusOverrides}
          />
        )
      ) : null}

      {query.tab === "dang-thuc-hien" ? (
        <div className="qv-dt">
          <div>
            {runs.status === "loading" ? (
              <p className="qv-status-line" role="status">
                Đang tải danh sách…
              </p>
            ) : runs.status === "error" ? (
              <p className="qv-inline-error" role="alert">
                Không thể tải danh sách luồng thực hiện.
              </p>
            ) : selectedRun ? (
              <SelectedRun
                auth={auth}
                card={cardFor(selectedRun)}
                clients={clients}
                key={selectedRun.id}
                measureHref={qdHref({ tab: "do-luong", run: null, rulesOpen: false })}
                nowMs={nowMs}
                onOpenMeasure={() => navigate({ tab: "do-luong", run: null, rulesOpen: false })}
                onOpenRun={(runId) => navigate({ tab: "dang-thuc-hien", run: runId })}
                onRefresh={refreshRuns}
                onState={setSelectedState}
                revertMeta={revertMeta[selectedRun.id] ?? null}
                run={selectedRun}
                startRevert={startRevert}
              />
            ) : query.run ? (
              <p className="qv-status-line" role="status">
                Đang tìm lượt chạy này…
              </p>
            ) : (
              <div className="qv-empty" role="status">
                <p>Chưa có quyết định nào đang thực hiện. Duyệt thẻ ở tab Đề xuất để Juli bắt đầu.</p>
              </div>
            )}
          </div>
          <RunQueue
            cardFor={cardFor}
            onSelect={(runId) => navigate({ run: runId })}
            runs={runList}
            selectedChip={selectedState && selectedState.runId === selectedRun?.id ? selectedState.chip : null}
            selectedId={selectedRun?.id ?? null}
          />
        </div>
      ) : null}

      {query.tab === "do-luong" ? (
        <DoLuongPanel
          items={measureItems}
          nowMs={nowMs}
          onKeep={onMeasureKeep}
          onOpenProposals={(event) => {
            event.preventDefault();
            navigate({ tab: "de-xuat", run: null });
          }}
          onOpenRun={(runId) => navigate({ tab: "dang-thuc-hien", run: runId })}
          onRevert={onMeasureRevert}
          onTab={(tab) => navigate({ measureTab: tab })}
          proposalsHref={qdHref({ tab: "de-xuat", run: null, rulesOpen: false })}
          tab={measureTab}
        />
      ) : null}
    </section>
  );
}

function SelectedRun({
  run,
  card,
  auth,
  clients,
  nowMs,
  revertMeta,
  measureHref,
  onOpenMeasure,
  onOpenRun,
  onRefresh,
  onState,
  startRevert,
}: {
  readonly run: QdRun;
  readonly card: CardView | null;
  readonly auth: AuthedOptions;
  readonly clients: QdClients;
  readonly nowMs: number | null;
  readonly revertMeta: { readonly reason: string; readonly startedAt: string } | null;
  readonly measureHref: string;
  readonly onOpenMeasure: () => void;
  readonly onOpenRun: (runId: string) => void;
  readonly onRefresh: () => void;
  readonly onState: (state: { runId: string; kind: RunKind; chip: Chip; headline?: string | null }) => void;
  readonly startRevert: (runId: string, choice: ReasonChoice) => Promise<{ runId: string } | { conflict: string } | { error: string }>;
}) {
  const { events, streamStatus } = clients.useRunEvents(run.id, auth, clients.streamFetch);
  const terminalSeen = events.some((event) => event.event_type === "workflow.completed" || event.event_type === "workflow.failed");
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
  }, [clients, auth, run.id, terminalSeen]);

  const isRevert = Boolean(changes?.reverts_run_id) || revertMeta !== null;
  const kind = runKind(run, card, events, isRevert);
  const [photoChecks, setPhotoChecks] = useState<readonly PhotoCheck[] | null>(null);
  const [detail, setDetail] = useState<RunDetail | null>(null);
  const runPhotos = detail?.photo ?? null;
  const shownChecks = photoChecks ?? (runPhotos && runPhotos.checks.length > 0 ? runPhotos.checks : null);
  const [photoState, setPhotoState] = useState<PhotoState>({ status: "idle" });
  const [appliedPosted, setAppliedPosted] = useState(false);
  const [appliedState, setAppliedState] = useState<{ busy: boolean; error: string | null }>({ busy: false, error: null });
  const [declined, setDeclined] = useState(false);
  const timeline = useMemo(
    () =>
      buildRunTimeline(events, {
        kind,
        isRevert: kind === "revert",
        awaiting: run.awaiting ?? null,
        photoChecks: shownChecks,
        revertStartedAt: revertMeta?.startedAt ?? (kind === "revert" ? run.created_at : null),
        revertReason: revertMeta?.reason ?? null,
        revertFieldLabels: changes?.changes.map((change) => change.label) ?? card?.changeLabels ?? [],
      }),
    [events, kind, run.awaiting, run.created_at, shownChecks, revertMeta, changes, card],
  );
  const phase = runPhase(run, kind, timeline, { appliedPosted, declined });
  // P14-E content runs: their phase and chip come from the run detail's `content`.
  const content = kind === "content" ? (detail?.content ?? null) : null;
  const cPhase = contentPhase(run, content, timeline, declined);
  const chip = kind === "content" ? contentChip(cPhase, run.stop_reason) : runChip(run, kind, phase);
  const headline = content?.headline ?? null;

  useEffect(() => {
    onState({ runId: run.id, kind, chip, headline });
    // chip is derived from kind/phase; compare by value to avoid loops
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run.id, kind, chip.label, chip.tone, headline]);

  // Cover-photo runs: the before/after URLs and the stored checks live on the
  // run detail (P10-B), not in the consent payload (`attach_staged_image`).
  // Content runs (P14-E): the steps, script and waits live there too, so the
  // detail is re-read whenever the run moves (status, awaiting, a new event).
  const wantsDetail = kind === "photo" || kind === "content";
  const consentSeen = timeline.pendingConsent !== null;
  const [detailKey, setDetailKey] = useState(0);
  const moves = kind === "content" ? `${run.status}:${events.length}` : "";
  useEffect(() => {
    if (!wantsDetail) return;
    let cancelled = false;
    clients
      .fetchRunDetail(auth, run.id)
      .then((data) => !cancelled && setDetail(data ?? null))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [clients, auth, run.id, wantsDetail, run.awaiting, consentSeen, terminalSeen, moves, detailKey]);

  // Seller Center instructions, once the run waits on the seller.
  const [instructions, setInstructions] = useState<LoadState<SellerInstructions> | null>(null);
  const wantsInstructions = run.awaiting === "seller_action";
  useEffect(() => {
    if (!wantsInstructions) return;
    let cancelled = false;
    clients
      .fetchInstructions(auth, run.id)
      .then((data) => !cancelled && setInstructions({ status: "ready", data }))
      .catch(() => !cancelled && setInstructions({ status: "error" }));
    return () => {
      cancelled = true;
    };
  }, [clients, auth, run.id, wantsInstructions]);

  const [revertBusy, setRevertBusy] = useState(false);
  const [revertConflict, setRevertConflict] = useState<string | null>(null);
  const [revertError, setRevertError] = useState<string | null>(null);

  const toolCallId = timeline.pendingConsent?.toolCallId ?? null;

  const declineRun = async (choice: ReasonChoice) => {
    try {
      await clients.decline(auth, run.id, choice);
    } catch (error) {
      // 404/409: nothing is waiting for the seller any more (decided elsewhere,
      // already resumed or ended) — the backend's own words are English codes.
      if (error instanceof QdApiError && (error.status === 404 || error.status === 409)) {
        onRefresh();
        throw new Error("Lượt chạy này không còn chờ bạn quyết định. Vui lòng tải lại trang.");
      }
      throw new Error(errorSentence(error, "Chưa gửi được lựa chọn. Vui lòng thử lại."));
    }
    setDeclined(true);
    onRefresh();
  };

  const analysisClients = useMemo(() => clients.analysisClients?.(auth) ?? null, [clients, auth]);

  if (kind === "content") {
    const act = async (action: () => Promise<void>) => {
      try {
        await action();
      } catch (error) {
        throw new Error(errorSentence(error, "Chưa gửi được. Vui lòng thử lại."));
      }
      onRefresh();
      setDetailKey((key) => key + 1);
    };
    return (
      <ContentRunPanel
        card={card}
        chip={chip}
        analysis={
          analysisClients && content ? <VideoAnalysis clients={analysisClients} target={{ kind: content.kind, runId: run.id }} /> : null
        }
        detail={content}
        measureHref={measureHref}
        onDecline={declineRun}
        onOpenMeasure={(event) => {
          event.preventDefault();
          onOpenMeasure();
        }}
        onPublished={() => act(() => clients.markPublished(auth, run.id))}
        onRedraft={() => act(() => clients.redraftContent(auth, run.id))}
        onUse={(version, edited) => act(() => clients.useContent(auth, run.id, version, edited))}
        phase={cPhase}
        reconnecting={streamStatus === "reconnecting"}
        run={run}
        timeline={timeline}
      />
    );
  }

  return (
    <RunPanel
      appliedState={appliedState}
      card={card}
      changes={changes}
      eventsLoaded={events.length > 0}
      instructions={instructions}
      kind={kind}
      measureHref={measureHref}
      nowMs={nowMs}
      onApplied={async () => {
        setAppliedState({ busy: true, error: null });
        try {
          await clients.markApplied(auth, run.id);
          setAppliedPosted(true);
          setAppliedState({ busy: false, error: null });
          onRefresh();
        } catch (error) {
          setAppliedState({ busy: false, error: errorSentence(error, "Chưa gửi được. Vui lòng thử lại.") });
        }
      }}
      onCancelRevert={async () => {
        if (!toolCallId) return;
        await clients.confirm(run.id, toolCallId, "decline", null, { token: auth.token, shopId: auth.shopId });
        setDeclined(true);
        onRefresh();
      }}
      onConfirm={async (callId, optionId, edited) => {
        await clients.confirm(run.id, callId, "approve", optionId, {
          token: auth.token,
          shopId: auth.shopId,
          editedValues: edited ?? undefined,
        });
        onRefresh();
      }}
      onDecline={declineRun}
      onOpenMeasure={(event) => {
        event.preventDefault();
        onOpenMeasure();
      }}
      onRevert={(choice) => {
        setRevertBusy(true);
        setRevertConflict(null);
        setRevertError(null);
        void startRevert(run.id, choice).then((result) => {
          setRevertBusy(false);
          if ("runId" in result) onOpenRun(result.runId);
          else if ("conflict" in result) setRevertConflict(result.conflict);
          else setRevertError(result.error);
        });
      }}
      onUpload={async (file) => {
        setPhotoState({ status: "uploading" });
        try {
          const checks = await clients.uploadPhoto(auth, run.id, file);
          setPhotoChecks(checks);
          setPhotoState({ status: "idle" });
          onRefresh();
        } catch (error) {
          const checks = error instanceof QdApiError ? photoChecksOf(error.body) : null;
          if (checks) setPhotoChecks(checks);
          setPhotoState({
            status: "error",
            message: checks
              ? "Ảnh chưa đạt yêu cầu. Vui lòng chọn ảnh khác."
              : errorSentence(error, "Chưa tải được ảnh lên. Vui lòng thử lại."),
          });
        }
      }}
      phase={phase}
      photoChecks={shownChecks}
      photoState={photoState}
      photoUrls={runPhotos ? { before: runPhotos.before_url, after: runPhotos.after_url } : null}
      reconnecting={streamStatus === "reconnecting"}
      revertBusy={revertBusy}
      revertConflict={revertConflict}
      revertError={revertError}
      revertReasonLabel={revertMeta?.reason ?? null}
      run={run}
      timeline={timeline}
    />
  );
}
