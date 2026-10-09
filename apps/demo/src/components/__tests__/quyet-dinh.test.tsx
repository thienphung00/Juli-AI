import type { AgentEvent, DemoDecisionItem, WorkflowRunListItem } from "@juli/contracts";
import { validateAgentEvent } from "@juli/contracts";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { QdApiError } from "../../lib/quyet-dinh/api-client";
import { DemoDecisionApproveError } from "../../lib/recommendations-api-client";
import { approveSequentially, groupStages, runStages } from "../../lib/quyet-dinh/batch";
import { batchCards, groupDecisions } from "../../lib/quyet-dinh/grouping";
import { buildRunTimeline, vnDate } from "../../lib/quyet-dinh/timeline";
import type { RevertQuestion, RunChanges, ShopRules } from "../../lib/quyet-dinh/types";
import { RunDetailPane, RunQueue } from "../quyet-dinh/dang-thuc-hien-panel";
import { DeXuatPanel } from "../quyet-dinh/de-xuat-panel";
import { DoLuongPanel, measurementLine } from "../quyet-dinh/do-luong-panel";
import { RulesEditor } from "../quyet-dinh/rules-editor";
import { REAL_QD_CLIENTS, SignedInQuyetDinh, type QdClients, type QdQuery } from "../quyet-dinh/signed-in-quyet-dinh";

/**
 * Quyết định (AC-8.7, ADR-109 d.6, 8–13): grouping, price exclusion, the
 * bands gate, sequential batch approve, the rules editor's set_by, the SSE
 * timeline (incl. the diagnoses soft-fail and a revert conflict), the ledger
 * sections, Hoàn tác 202/409, the Đo lường placeholder and question dismiss.
 */

vi.mock("next/navigation", () => ({
  usePathname: () => "/decisions",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

// -- fixtures -------------------------------------------------------------------

function item({
  id,
  stage = "page",
  scope = "PRODUCT_CARD",
  lever = "description",
  executable = true,
  gmv = 10_000,
  name = `Sản phẩm ${id}`,
}: {
  id: string;
  stage?: string;
  scope?: string;
  lever?: string;
  executable?: boolean;
  gmv?: number | null;
  name?: string;
}): DemoDecisionItem {
  return {
    id,
    title: `Tối ưu ${name}`,
    description: "",
    severity: "high",
    priority: 1,
    computed_at: null,
    surfaced_at: null,
    is_executable: executable,
    recommendation: {
      source_kpi_ids: [],
      diagnosis: {
        version: "adr106-v1",
        as_of: "2026-10-08",
        rank: 1,
        status: "rule",
        status_label: "Theo quy tắc",
        stage: { code: stage, label: "Nhấp → Đặt hàng (trang sản phẩm)" },
        lever: {
          code: lever,
          label: lever,
          action: lever === "product_discount" ? "Giảm giá sản phẩm" : "Viết lại mô tả",
          detail: "180 → 640 ký tự, thêm cách dùng",
          evidence: [{ code: "DESC_LESS_THAN_FIVE_HUNDRED_CHARS", source: "tiktok", detail: "Mô tả quá ngắn" }],
        },
        main_kpi: { key: "ctor", label: "CTOR", value: "2,1 %" },
        trigger: { code: "below_median", gap: -0.3, sentence: "Thấp hơn 31 % so với trung bình shop" },
        channel_scope: scope,
        recoverable_gmv_per_day: gmv,
        product_title: name,
        tiktok_product_id: `1729${id}000001`,
      },
    },
  };
}

function rules(bands: Record<string, number> = {}): ShopRules {
  const unset = { value: null, set_by: null, set_by_user_id: null, set_at: null };
  return {
    stability_band: Object.fromEntries(
      Object.entries(bands).map(([metric, value]) => [
        metric,
        { value, set_by: "team" as const, set_by_user_id: "u1", set_at: "2026-10-08T03:00:00Z" },
      ]),
    ),
    product_cost: {},
    max_discount_pct: {},
    min_margin_pct: null,
    max_open_cards: { ...unset, value: 5 },
    auto_levers: { ...unset, value: ["attributes", "description", "image", "title"] },
    protected_terms: { ...unset, value: [] },
    band_metrics: ["impressions", "ctr", "conversion_rate", "items_sold", "gmv", "sku_orders", "gmv_per_order"],
    listing_levers: ["title", "description", "attributes", "image"],
  };
}

const RUN_ID = "11111111-1111-4111-8111-111111111111";

function ev(seq: number, event_type: string, payload: Record<string, unknown>, second = seq): AgentEvent {
  return validateAgentEvent({
    workflow_run_id: RUN_ID,
    sequence_number: seq,
    event_type,
    timestamp: `2026-10-08T03:01:${String(second).padStart(2, "0")}Z`,
    payload,
    v: 1,
  });
}

/** A recorded Optimize Product run up to the consent pause, with the diagnoses soft-fail. */
const PAUSED_RUN: AgentEvent[] = [
  ev(1, "workflow.started", { workflow_key: "optimize_product_2", product_ref: "p", prompt_version: "v3" }),
  ev(2, "tool.started", { tool_call_id: "c0", tool_name: "get_product_diagnoses" }),
  ev(3, "tool.completed", {
    tool_call_id: "c0",
    tool_name: "get_product_diagnoses",
    ok: true,
    summary: "Không đọc được chẩn đoán TikTok — tiếp tục với thông tin sản phẩm",
  }),
  ev(4, "tool.started", { tool_call_id: "c1", tool_name: "get_product_information" }),
  ev(5, "tool.completed", { tool_call_id: "c1", tool_name: "get_product_information", ok: true, summary: "Hoàn tất" }),
  ev(6, "workflow.approval_required", {
    tool_call_id: "c2",
    tool_name: "update_product_listing",
    proposed_change: { description: "Mô tả mới" },
    expires_at: "2026-10-08T07:01:06Z",
    options: [{ option_id: "1", proposed_change: { description: "Mô tả mới" }, rationale: "Đủ ý", params_sha: "x" }],
  }),
];

const FINISHED_RUN: AgentEvent[] = [
  ...PAUSED_RUN,
  ev(7, "workflow.status", { phase_narration: "Đã xác nhận" }),
  ev(8, "tool.started", { tool_call_id: "c2", tool_name: "update_product_listing" }),
  ev(9, "tool.completed", { tool_call_id: "c2", tool_name: "update_product_listing", ok: true, summary: "Hoàn tất" }),
  ev(10, "tool.started", { tool_call_id: "c3", tool_name: "check_product_status" }),
  ev(11, "tool.completed", { tool_call_id: "c3", tool_name: "check_product_status", ok: true, summary: "Hoàn tất" }),
  ev(12, "workflow.completed", { stop_reason: "final_response" }),
];

/** A revert run refused at the write: the field changed externally after Juli's write. */
const REVERT_CONFLICT: AgentEvent[] = [
  ev(1, "workflow.started", { workflow_key: "optimize_product_2", product_ref: "p", prompt_version: "v3" }),
  ev(2, "tool.started", { tool_call_id: "r1", tool_name: "get_product_information" }),
  ev(3, "tool.completed", { tool_call_id: "r1", tool_name: "get_product_information", ok: true, summary: "Hoàn tất" }),
  ev(4, "workflow.failed", { status: "failed", stop_reason: "concurrency_conflict" }),
];

function run(overrides: Partial<WorkflowRunListItem> & { id: string }): WorkflowRunListItem {
  return {
    status: "completed",
    stop_reason: "final_response",
    product_name: `Sản phẩm ${overrides.id}`,
    created_at: "2026-10-08T03:00:00Z",
    completed_at: "2026-10-08T03:05:00Z",
    running_seconds_elapsed: 0,
    latest_narration: null,
    decision_summary: null,
    ...overrides,
  };
}

function changes(overrides: Partial<RunChanges> = {}): RunChanges {
  return {
    run_id: RUN_ID,
    reverts_run_id: null,
    changes: [
      {
        field: "description",
        label: "Mô tả",
        before: "Mô tả cũ",
        after: "Mô tả mới",
        after_source: "read",
        recorded_at: "2026-10-08T03:01:09Z",
      },
    ],
    revert: { available: true, reason_code: null, message: null, runs: [] },
    question: null,
    ...overrides,
  };
}

// -- grouping / price exclusion ------------------------------------------------------

describe("Đề xuất grouping", () => {
  it("groups by stream × weak stage, sums recoverable GMV/day × 30, keeps backend order", () => {
    const groups = groupDecisions([
      item({ id: "a", gmv: 20_000 }),
      item({ id: "b", stage: "card", lever: "title" }),
      item({ id: "c", gmv: 10_000, lever: "product_discount", executable: false }),
      item({ id: "d", scope: "ALL_CHANNELS", stage: "page" }),
    ]);
    expect(groups.map((group) => group.title)).toEqual([
      "2 thẻ tối ưu để nâng CTOR Thẻ sản phẩm",
      "1 thẻ tối ưu để nâng CTR Thẻ sản phẩm",
      "1 thẻ tối ưu để nâng CTOR (mọi kênh)",
    ]);
    expect(groups[0].gmvPerMonth).toBe(900_000);
    expect(groups[0].cards.map((card) => card.executable)).toEqual([true, false]);
  });

  it("excludes price / non-executable cards from the batch, and approved or dropped ones", () => {
    const [group] = groupDecisions([
      item({ id: "a" }),
      item({ id: "b" }),
      item({ id: "c", lever: "product_discount", executable: true }),
    ]);
    expect(batchCards(group, new Set()).map((card) => card.id)).toEqual(["a", "b"]);
    expect(batchCards(group, new Set(["a"])).map((card) => card.id)).toEqual(["b"]);
  });
});

function renderDeXuat(overrides: Partial<React.ComponentProps<typeof DeXuatPanel>> = {}) {
  const props: React.ComponentProps<typeof DeXuatPanel> = {
    groups: groupDecisions([item({ id: "a" }), item({ id: "b" }), item({ id: "c", lever: "product_discount", executable: false })]),
    rules: rules({ ctr: 3 }),
    rulesStatus: "ready",
    approvedIds: new Set(),
    droppedIds: new Set(),
    busy: false,
    progress: null,
    onApprove: vi.fn(),
    onDrop: vi.fn(),
    onOpenRules: vi.fn(),
    ...overrides,
  };
  render(<DeXuatPanel {...props} />);
  return props;
}

describe("Đề xuất panel", () => {
  it("renders compact cards; the price card says 'Bạn áp dụng trên Seller Center' and is not counted", async () => {
    const props = renderDeXuat();
    const group = screen.getByTestId("decision-group");
    expect(within(group).getByRole("heading", { level: 2 })).toHaveTextContent("3 thẻ tối ưu để nâng CTOR Thẻ sản phẩm");
    expect(within(group).getByTestId("group-gmv")).toHaveTextContent("GMV dự kiến");
    expect(within(group).getByTestId("group-gmv")).toHaveTextContent("ước tính theo quy tắc");
    const price = screen.getByRole("article", { name: "Sản phẩm c" });
    expect(price).toHaveTextContent("Bạn áp dụng trên Seller Center");
    expect(within(price).queryByRole("button", { name: "Duyệt thẻ này" })).toBeNull();
    const card = screen.getByRole("article", { name: "Sản phẩm a" });
    expect(card).toHaveTextContent("KPI chính · CTOR");
    expect(card).toHaveTextContent("Mô tả quá ngắn");
    expect(card).toHaveTextContent("Viết lại mô tả");
    // Stepper on the group: Đề xuất is the current stage.
    expect(within(group).getByRole("list", { name: /^Tiến trình/ }).querySelector('[aria-current="step"]')).toHaveTextContent("Đề xuất");

    await userEvent.click(within(group).getByRole("button", { name: "Duyệt 2 thẻ" }));
    await userEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Duyệt" }));
    expect(props.onApprove).toHaveBeenCalledWith(["a", "b"]);
  });

  it("blocks Duyệt N thẻ until a stability band is set, and asks for one", async () => {
    const props = renderDeXuat({ rules: rules() });
    expect(screen.getByRole("button", { name: "Duyệt 2 thẻ" })).toBeDisabled();
    expect(screen.getAllByText("Đặt ngưỡng giữ ổn định trước khi chạy").length).toBeGreaterThan(0);
    await userEvent.click(screen.getByRole("button", { name: "Đặt ngưỡng" }));
    expect(props.onOpenRules).toHaveBeenCalled();
  });

  it("shows the seller's bands and rule chips with who set them", () => {
    const r = rules({ ctr: 3, impressions: 5 });
    renderDeXuat({ rules: { ...r, max_open_cards: { value: 3, set_by: "seller", set_by_user_id: "u", set_at: "2026-10-08T00:00:00Z" } } });
    expect(screen.getByTestId("stability-card")).toHaveTextContent("CTR · ±3 %");
    expect(screen.getByTestId("stability-card")).toHaveTextContent("Lượt hiển thị sản phẩm · ±5 %");
    expect(screen.getByTestId("rules-chips")).toHaveTextContent("≤ 3 thẻ mở cùng lúc · Bạn đặt");
  });
});

// -- batch sequencing ---------------------------------------------------------------------

describe("batch approve", () => {
  it("approves one card at a time, in order, and continues past a failure", async () => {
    let inFlight = 0;
    let maxInFlight = 0;
    const calls: string[] = [];
    const approve = vi.fn(async (id: string) => {
      inFlight += 1;
      maxInFlight = Math.max(maxInFlight, inFlight);
      calls.push(id);
      await new Promise((resolve) => setTimeout(resolve, 1));
      inFlight -= 1;
      if (id === "b") throw new DemoDecisionApproveError(409);
      return { runId: `run-${id}` };
    });
    const results = await approveSequentially(["a", "b", "c"], approve);
    expect(calls).toEqual(["a", "b", "c"]);
    expect(maxInFlight).toBe(1);
    expect(results.map((r) => r.runId)).toEqual(["run-a", null, "run-c"]);
  });

  it("stepper state reflects the group's / run's own state", () => {
    expect(groupStages(0, 2)).toEqual(["done", "current", "todo", "todo", "todo"]);
    expect(groupStages(2, 2)[3]).toBe("current");
    expect(runStages({ status: "waiting_approval", stop_reason: null })[2]).toBe("current");
    expect(runStages({ status: "completed", stop_reason: "final_response" })[4]).toBe("current");
    expect(runStages({ status: "failed", stop_reason: "concurrency_conflict" })[3]).toBe("failed");
  });
});

// -- rules editor ---------------------------------------------------------------------------

describe("rules editor", () => {
  it("saves as the seller by default and as the team with the toggle; 422 shows inline", async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(<RulesEditor onDelete={vi.fn()} onSave={onSave} rules={rules({ ctr: 3 })} />);
    expect(screen.getByTestId("rule-stability_band-ctr")).toHaveTextContent("Đội ngũ Juli đặt · 08/10/2026");
    expect(screen.getByTestId("rule-max_open_cards")).toHaveTextContent("Mặc định");

    const impressions = screen.getByTestId("rule-stability_band-impressions");
    await userEvent.type(within(impressions).getByRole("textbox"), "3,5");
    await userEvent.click(within(impressions).getByRole("button", { name: "Lưu" }));
    expect(onSave).toHaveBeenLastCalledWith("stability_band", 3.5, "seller", "impressions");

    await userEvent.click(screen.getByRole("checkbox", { name: "Điền thay Seller (đội ngũ Juli)" }));
    expect(screen.getByTestId("set-by-mode")).toHaveTextContent("Đội ngũ Juli đặt");
    await userEvent.click(within(impressions).getByRole("button", { name: "Lưu" }));
    expect(onSave).toHaveBeenLastCalledWith("stability_band", 3.5, "team", "impressions");

    onSave.mockRejectedValueOnce(new QdApiError(422, null, "max_open_cards: value must be between 1 and 5"));
    const cards = screen.getByTestId("rule-max_open_cards");
    await userEvent.type(within(cards).getByRole("textbox"), "9");
    await userEvent.click(within(cards).getByRole("button", { name: "Lưu" }));
    expect(await within(cards).findByRole("alert")).toHaveTextContent("Số thẻ mở cùng lúc phải là số nguyên từ 1 đến 5.");
  });
});

// -- timeline ------------------------------------------------------------------------------

describe("run timeline from the SSE events", () => {
  it("maps tools to steps, keeps the diagnoses soft-fail line, pauses at the consent step", () => {
    const timeline = buildRunTimeline(PAUSED_RUN);
    expect(timeline.steps.map((step) => [step.label, step.status])).toEqual([
      ["Đọc chẩn đoán TikTok", "done"],
      ["Đọc thông tin sản phẩm", "done"],
      ["Xác nhận một lần", "current"],
      ["Ghi lên TikTok Shop", "upcoming"],
      ["TikTok duyệt lại trang sản phẩm", "upcoming"],
      ["Kết thúc · đặt lịch đo", "upcoming"],
    ]);
    expect(timeline.steps[0].detail).toBe("Không đọc được chẩn đoán TikTok — tiếp tục với thông tin sản phẩm");
    expect(timeline.steps[0].at).toBe("2026-10-08T03:01:03Z");
    expect(timeline.steps[2].detail).toBe("Thay đổi: Mô tả");
    expect(timeline.pendingConsent?.toolCallId).toBe("c2");
    expect(timeline.steps.filter((step) => step.status === "upcoming").every((step) => step.at === null)).toBe(true);
  });

  it("is idempotent under duplicates and reorder; terminal gives day 7 / day 14 from completion", () => {
    const shuffled = [...FINISHED_RUN].reverse().concat(FINISHED_RUN.slice(0, 3));
    const timeline = buildRunTimeline(shuffled);
    expect(timeline.pendingConsent).toBeNull();
    expect(timeline.steps.every((step) => step.status === "done")).toBe(true);
    expect(timeline.steps.at(-1)?.label).toBe("Kết thúc · đặt lịch đo");
    expect(timeline.steps.at(-1)?.detail).toBe("Đo sơ bộ ngày 15/10/2026 (ngày 7), chốt ngày 22/10/2026 (ngày 14).");
    expect(timeline.steps.find((step) => step.kind === "consent")?.detail).toBe("Thay đổi: Mô tả");
  });

  it("a revert refused for an external change ends failed and says Juli does not overwrite", () => {
    const timeline = buildRunTimeline(REVERT_CONFLICT, { isRevert: true });
    const last = timeline.steps.at(-1)!;
    expect(last.status).toBe("failed");
    expect(last.label).toBe("Kết thúc lượt chạy");
    expect(last.detail).toContain("Juli không ghi đè");
    expect(timeline.terminal?.day7).toBeNull();
  });

  it("renders the consent picker inline and the step times in Vietnam time", () => {
    render(
      <RunDetailPane
        changes={null}
        confirm={vi.fn()}
        events={PAUSED_RUN}
        isRevert={false}
        nowMs={Date.parse("2026-10-08T03:02:00Z")}
        onRevert={vi.fn()}
        reconnecting={false}
        revertState={{ status: "idle" }}
        run={run({ id: RUN_ID, status: "waiting_approval", stop_reason: null, completed_at: null })}
      />,
    );
    const timeline = screen.getByTestId("run-timeline");
    const current = timeline.querySelector('[aria-current="step"]') as HTMLElement;
    expect(current).toHaveTextContent("Xác nhận một lần");
    expect(within(current).getByRole("button", { name: "Xác nhận phương án này" })).toBeInTheDocument();
    expect(within(timeline).getAllByText("10:01:03").length).toBe(1);
  });
});

// -- ledger + Hoàn tác -------------------------------------------------------------------------

describe("Hàng chờ thẻ tối ưu", () => {
  it("keeps the ledger sections and honest terminal labels", () => {
    render(
      <RunQueue
        onSelect={vi.fn()}
        runs={[
          run({ id: "r1", status: "running", stop_reason: null }),
          run({ id: "r2", status: "waiting_approval", stop_reason: null }),
          run({ id: "r3" }),
          run({ id: "r4", status: "completed", stop_reason: "confirmation_declined" }),
          run({ id: "r5", status: "failed", stop_reason: "worker_lost" }),
        ]}
        selectedId="r3"
      />,
    );
    const sections = screen.getAllByRole("region").map((section) => section.getAttribute("aria-label"));
    expect(sections).toEqual(["Đang chờ bạn", "Đang chạy", "Hoàn tất"]);
    const finished = screen.getByRole("region", { name: "Hoàn tất" });
    expect(finished).toHaveTextContent("Hoàn tất — không đổi");
    expect(finished).toHaveTextContent("Sự cố");
    expect(screen.getByRole("button", { name: /Sản phẩm r3/ })).toHaveAttribute("aria-pressed", "true");
  });
});

function sseResponse(events: readonly AgentEvent[]): Response {
  const text = events
    .map((e) => `id: ${e.sequence_number}\nevent: ${e.event_type}\ndata: ${JSON.stringify(e)}\n\n`)
    .join("");
  return new Response(text, { status: 200, headers: { "Content-Type": "text/event-stream" } });
}

function stubClients(overrides: Partial<QdClients> = {}): QdClients {
  return {
    ...REAL_QD_CLIENTS,
    fetchDecisions: vi.fn().mockResolvedValue([item({ id: "a" }), item({ id: "b" })]),
    approve: vi.fn(async (id: string) => ({ runId: `run-${id}` })),
    fetchRuns: vi.fn().mockResolvedValue([run({ id: RUN_ID })]),
    fetchRules: vi.fn().mockResolvedValue(rules({ ctr: 3 })),
    putRule: vi.fn().mockResolvedValue(undefined),
    deleteRule: vi.fn().mockResolvedValue(undefined),
    fetchChanges: vi.fn().mockResolvedValue(changes()),
    startRevert: vi.fn().mockResolvedValue({ runId: "new-revert-run" }),
    fetchQuestions: vi.fn().mockResolvedValue([]),
    dismissQuestion: vi.fn().mockResolvedValue(undefined),
    confirm: vi.fn(),
    streamFetch: vi.fn(async () => sseResponse(FINISHED_RUN)) as unknown as typeof fetch,
    ...overrides,
  };
}

function renderSignedIn(query: Partial<QdQuery>, clients: QdClients) {
  const onNavigate = vi.fn();
  render(
    <SignedInQuyetDinh
      clients={clients}
      onNavigate={onNavigate}
      query={{ tab: "de-xuat", run: null, rulesOpen: false, ...query }}
      shop={{ id: "shop-1", name: "Shop Minh Anh" }}
      token="tok"
    />,
  );
  return onNavigate;
}

describe("signed-in Quyết định", () => {
  it("Duyệt N thẻ approves sequentially and opens Đang thực hiện on the first new run", async () => {
    const clients = stubClients();
    const onNavigate = renderSignedIn({}, clients);
    await userEvent.click(await screen.findByRole("button", { name: "Duyệt 2 thẻ" }));
    await userEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Duyệt" }));
    await waitFor(() => expect(onNavigate).toHaveBeenCalledWith("/decisions?tab=dang-thuc-hien&run=run-a"));
    expect((clients.approve as ReturnType<typeof vi.fn>).mock.calls.map((call) => call[0])).toEqual(["a", "b"]);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("2 thẻ tối ưu để nâng CTOR Thẻ sản phẩm");
  });

  it("a finished run shows its replayed timeline, before → after and Hoàn tác (202 → the new run)", async () => {
    const clients = stubClients();
    const onNavigate = renderSignedIn({ tab: "dang-thuc-hien", run: RUN_ID }, clients);
    const changesBlock = await screen.findByTestId("run-changes");
    expect(changesBlock).toHaveTextContent("Mô tả cũ");
    expect(changesBlock).toHaveTextContent("Mô tả mới");
    expect(screen.getByTestId("run-timeline")).toHaveTextContent("Đo sơ bộ ngày 15/10/2026 (ngày 7)");
    await userEvent.click(within(changesBlock).getByRole("button", { name: "Hoàn tác" }));
    await waitFor(() => expect(onNavigate).toHaveBeenCalledWith("/decisions?tab=dang-thuc-hien&run=new-revert-run"));
  });

  it("Hoàn tác 409 shows the backend's Vietnamese message verbatim", async () => {
    const message = "Mô tả đã được sửa bên ngoài sau khi Juli ghi. Juli không ghi đè thay đổi đó.";
    const clients = stubClients({ startRevert: vi.fn().mockRejectedValue(new QdApiError(409, "external_change", message)) });
    renderSignedIn({ tab: "dang-thuc-hien", run: RUN_ID }, clients);
    const block = await screen.findByTestId("run-changes");
    await userEvent.click(within(block).getByRole("button", { name: "Hoàn tác" }));
    expect(await within(block).findByRole("alert")).toHaveTextContent(message);
  });

  it("Hoàn tác is disabled with the reason when the backend says it is not available", async () => {
    const reason = "Lượt chạy này đã được hoàn tác.";
    const clients = stubClients({
      fetchChanges: vi.fn().mockResolvedValue(
        changes({ revert: { available: false, reason_code: "already_reverted", message: reason, runs: [] } }),
      ),
    });
    renderSignedIn({ tab: "dang-thuc-hien", run: RUN_ID }, clients);
    const block = await screen.findByTestId("run-changes");
    expect(within(block).getByRole("button", { name: "Hoàn tác" })).toBeDisabled();
    expect(block).toHaveTextContent(reason);
  });

  it("Đo lường: placeholder before day 7, Hoàn tác? questions, Giữ thay đổi dismisses", async () => {
    const question: RevertQuestion = {
      id: "q1",
      run_id: RUN_ID,
      status: "open",
      breaches: [{ metric: "ctr", impact_pct: -5.2, band_pct: 3 }],
      created_at: "2026-10-15T00:00:00Z",
      revert_run_id: null,
    };
    const clients = stubClients({ fetchQuestions: vi.fn().mockResolvedValue([question]) });
    renderSignedIn({ tab: "do-luong" }, clients);
    const questions = await screen.findByTestId("revert-questions");
    expect(questions).toHaveTextContent("CTR lệch −5,2 % (ngưỡng ±3 %)");
    const measure = screen.getByTestId("measure-list");
    await waitFor(() => expect(measure).toHaveTextContent("Mô tả"));
    expect(measure).not.toHaveTextContent("giờ nhân sự");
    await userEvent.click(within(questions).getByRole("button", { name: "Giữ thay đổi" }));
    await waitFor(() => expect(screen.queryByTestId("revert-questions")).toBeNull());
    expect(clients.dismissQuestion).toHaveBeenCalledWith({ token: "tok", shopId: "shop-1" }, "q1");
  });

  it("the rules editor opens from the URL and saves through the rules client", async () => {
    const clients = stubClients();
    renderSignedIn({ rulesOpen: true }, clients);
    const editor = await screen.findByTestId("rules-editor");
    await userEvent.click(within(editor).getByRole("checkbox", { name: "Điền thay Seller (đội ngũ Juli)" }));
    const gmv = within(editor).getByTestId("rule-stability_band-gmv");
    await userEvent.type(within(gmv).getByRole("textbox"), "3");
    await act(async () => {
      await userEvent.click(within(gmv).getByRole("button", { name: "Lưu" }));
    });
    expect(clients.putRule).toHaveBeenCalledWith({ token: "tok", shopId: "shop-1" }, "stability_band", 3, "team", "gmv");
  });
});

describe("Đo lường placeholder", () => {
  it("says when day 7 is, with no number, before day 7", () => {
    expect(measurementLine("2026-10-08T03:05:00Z", Date.parse("2026-10-10T00:00:00Z"))).toBe(
      "Đang chờ đủ 7 ngày dữ liệu · đo lúc 15/10/2026",
    );
    expect(vnDate("2026-10-08T20:00:00Z")).toBe("09/10/2026");
    render(
      <DoLuongPanel
        changesByRun={{}}
        nowMs={Date.parse("2026-10-10T00:00:00Z")}
        onDismissQuestion={vi.fn()}
        onOpenRun={vi.fn()}
        onRevertQuestion={vi.fn()}
        questionStates={{}}
        questions={[]}
        runs={[run({ id: "r1" }), run({ id: "r2", stop_reason: "confirmation_declined" })]}
      />,
    );
    const rows = screen.getAllByRole("listitem");
    expect(rows).toHaveLength(1);
    expect(rows[0]).toHaveTextContent("Đang chờ đủ 7 ngày dữ liệu · đo lúc 15/10/2026");
  });
});
