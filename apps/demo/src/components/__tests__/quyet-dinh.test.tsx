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
import { RunQueue } from "../quyet-dinh/dang-thuc-hien-panel";
import { measurementLine } from "../quyet-dinh/do-luong-panel";
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


// -- timeline (AC-10.3: artboard copy — intentional update of the P8-F strings) ---------------------

describe("run timeline from the SSE events", () => {
  it("maps tools to the plan rows, keeps the diagnoses soft-fail line, pauses at the consent step", () => {
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
    expect(timeline.steps[2].detail).toBe("Đang chờ bạn");
    expect(timeline.pendingConsent?.toolCallId).toBe("c2");
    expect(timeline.steps.filter((step) => step.status === "upcoming").every((step) => step.at === null)).toBe(true);
  });

  it("is idempotent under duplicates and reorder; terminal gives day 7 / day 14 from completion", () => {
    const shuffled = [...FINISHED_RUN].reverse().concat(FINISHED_RUN.slice(0, 3));
    const timeline = buildRunTimeline(shuffled);
    expect(timeline.pendingConsent).toBeNull();
    expect(timeline.steps.every((step) => step.status === "done")).toBe(true);
    expect(timeline.steps.at(-1)?.label).toBe("Kết thúc · đặt lịch đo");
    expect(timeline.steps.at(-1)?.detail).toBe("Đo sơ bộ 15/10 (ngày 7) · chốt 22/10 (ngày 14)");
    expect(timeline.steps.find((step) => step.kind === "consent")?.detail).toBe("Bạn đã xác nhận");
  });

  it("Không thực hiện: the steps after the consent read Bỏ qua", () => {
    const timeline = buildRunTimeline([...PAUSED_RUN, ev(7, "workflow.completed", { stop_reason: "confirmation_declined" })]);
    expect(timeline.steps.find((step) => step.kind === "consent")?.detail).toBe("Bạn chọn không thực hiện");
    const after = timeline.steps.slice(timeline.steps.findIndex((step) => step.kind === "consent") + 1);
    expect(after.map((step) => [step.status, step.detail])).toEqual([
      ["skipped", "Bỏ qua"],
      ["skipped", "Bỏ qua"],
      ["skipped", "Bỏ qua"],
    ]);
  });

  it("a revert refused for an external change stops at 'Kiểm tra có ai sửa ngoài Juli'", () => {
    const timeline = buildRunTimeline(REVERT_CONFLICT, { isRevert: true, revertFieldLabels: ["Tiêu đề"] });
    const check = timeline.steps.find((step) => step.label === "Kiểm tra có ai sửa ngoài Juli")!;
    expect(check.status).toBe("failed");
    expect(check.detail).toBe("Tiêu đề đã bị sửa ngoài Juli — dừng");
    expect(timeline.steps.at(-1)).toMatchObject({ label: "Kết thúc · dừng đo", status: "skipped", detail: "Bỏ qua" });
    expect(timeline.terminal?.day7).toBeNull();
  });
});

// -- queue --------------------------------------------------------------------------------------

describe("Hàng chờ thẻ tối ưu", () => {
  it("lists every run with its honest chip, the one waiting on the seller first", () => {
    render(
      <RunQueue
        cardFor={() => null}
        onSelect={vi.fn()}
        runs={[
          run({ id: "r1", status: "running", stop_reason: null }),
          run({ id: "r2", status: "waiting_approval", stop_reason: null }),
          run({ id: "r3" }),
          run({ id: "r4", status: "completed", stop_reason: "confirmation_declined" }),
          run({ id: "r5", status: "queued", stop_reason: null }),
        ]}
        selectedChip={null}
        selectedId="r3"
      />,
    );
    const rows = screen.getAllByRole("button").map((button) => button.textContent);
    expect(rows[0]).toBe("Sản phẩm r2Đang chờ bạn");
    expect(rows[1]).toBe("Sản phẩm r1Đang chạy");
    expect(rows[2]).toBe("Sản phẩm r5Trong hàng đợi");
    expect(rows).toContain("Sản phẩm r3Đã áp dụng");
    expect(rows).toContain("Sản phẩm r4Không thay đổi");
    expect(screen.getByRole("button", { name: /Sản phẩm r3/ })).toHaveAttribute("aria-pressed", "true");
  });
});

// -- signed in --------------------------------------------------------------------------------------

function sseResponse(events: readonly AgentEvent[]): Response {
  const text = events.map((e) => `id: ${e.sequence_number}\nevent: ${e.event_type}\ndata: ${JSON.stringify(e)}\n\n`).join("");
  return new Response(text, { status: 200, headers: { "Content-Type": "text/event-stream" } });
}

function stubClients(overrides: Partial<QdClients> = {}): QdClients {
  return {
    ...REAL_QD_CLIENTS,
    fetchDecisions: vi.fn().mockResolvedValue([item({ id: "a" }), item({ id: "b" })]),
    approve: vi.fn(async (id: string) => ({ runId: `run-${id}` })),
    reject: vi.fn().mockResolvedValue({ status: "rejected", cooldown_until: null }),
    fetchRuns: vi.fn().mockResolvedValue([run({ id: RUN_ID })]),
    fetchRules: vi.fn().mockResolvedValue(rules({ ctr: 3 })),
    putRule: vi.fn().mockResolvedValue(undefined),
    deleteRule: vi.fn().mockResolvedValue(undefined),
    fetchChanges: vi.fn().mockResolvedValue(changes()),
    startRevert: vi.fn().mockResolvedValue({ runId: "new-revert-run" }),
    fetchQuestions: vi.fn().mockResolvedValue([]),
    dismissQuestion: vi.fn().mockResolvedValue(undefined),
    confirm: vi.fn(),
    decline: vi.fn().mockResolvedValue({ status: "declined", cooldown_until: null }),
    uploadPhoto: vi.fn().mockResolvedValue([]),
    fetchInstructions: vi.fn().mockResolvedValue({ steps: [], deep_link: null, summary: "" }),
    markApplied: vi.fn().mockResolvedValue(undefined),
    fetchMeasurement: vi.fn().mockResolvedValue(null),
    fetchRunDetail: vi.fn().mockResolvedValue(null),
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

  it("blocks Phê duyệt and Duyệt N thẻ until a stability band is set", async () => {
    renderSignedIn({}, stubClients({ fetchRules: vi.fn().mockResolvedValue(rules()) }));
    expect(await screen.findByRole("button", { name: "Duyệt 2 thẻ" })).toBeDisabled();
    for (const button of screen.getAllByRole("button", { name: "Phê duyệt" })) expect(button).toBeDisabled();
    expect(screen.getByRole("button", { name: "Đặt ngưỡng" })).toBeInTheDocument();
  });

  it("a finished run shows the done panel and Hoàn tác asks one reason (202 → the new run)", async () => {
    const clients = stubClients();
    const onNavigate = renderSignedIn({ tab: "dang-thuc-hien", run: RUN_ID }, clients);
    const done = await screen.findByTestId("run-done");
    expect(done).toHaveTextContent("Đã áp dụng · thẻ chuyển sang Đo lường");
    expect(done).toHaveTextContent("Đã đổi: Mô tả. Giá trị cũ đã được lưu. Đo sơ bộ 15/10/2026 (ngày 7), chốt 22/10/2026 (ngày 14).");
    expect(screen.getByTestId("run-timeline")).toHaveTextContent("Đo sơ bộ 15/10 (ngày 7) · chốt 22/10 (ngày 14)");
    await userEvent.click(within(done).getByRole("button", { name: "Hoàn tác" }));
    const dialog = screen.getByRole("dialog", { name: "Hoàn tác thay đổi này?" });
    expect(within(dialog).getByRole("button", { name: "Bắt đầu hoàn tác" })).toBeDisabled();
    await userEvent.click(within(dialog).getByRole("radio", { name: "Khách phản hồi không tốt" }));
    await userEvent.click(within(dialog).getByRole("button", { name: "Bắt đầu hoàn tác" }));
    await waitFor(() => expect(onNavigate).toHaveBeenCalledWith("/decisions?tab=dang-thuc-hien&run=new-revert-run"));
    expect(clients.startRevert).toHaveBeenCalledWith({ token: "tok", shopId: "shop-1" }, RUN_ID, { reason_code: "bad_feedback" });
  });

  it("Hoàn tác 409 external_change: Juli stops, the backend's sentence verbatim", async () => {
    const message = "Mô tả đã được sửa bên ngoài sau khi Juli ghi. Juli không ghi đè thay đổi đó.";
    const clients = stubClients({ startRevert: vi.fn().mockRejectedValue(new QdApiError(409, "external_change", message)) });
    renderSignedIn({ tab: "dang-thuc-hien", run: RUN_ID }, clients);
    await userEvent.click(within(await screen.findByTestId("run-done")).getByRole("button", { name: "Hoàn tác" }));
    await userEvent.click(screen.getByRole("radio", { name: "TikTok cảnh báo sản phẩm" }));
    await userEvent.click(screen.getByRole("button", { name: "Bắt đầu hoàn tác" }));
    const conflict = await screen.findByTestId("revert-conflict");
    expect(conflict).toHaveTextContent("Juli dừng, không ghi đè");
    expect(conflict).toHaveTextContent(message);
  });

  it("Hoàn tác is disabled with the reason when the backend says it is not available", async () => {
    const reason = "Lượt chạy này đã được hoàn tác.";
    const clients = stubClients({
      fetchChanges: vi.fn().mockResolvedValue(changes({ revert: { available: false, reason_code: "already_reverted", message: reason, runs: [] } })),
    });
    renderSignedIn({ tab: "dang-thuc-hien", run: RUN_ID }, clients);
    const done = await screen.findByTestId("run-done");
    await waitFor(() => expect(within(done).getByRole("button", { name: "Hoàn tác" })).toBeDisabled());
    expect(done).toHaveTextContent(reason);
  });

  it("Đo lường without a measurement endpoint: the waiting line, a P8 question, Giữ thay đổi dismisses", async () => {
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
    const ask = await screen.findByTestId("day7-ask");
    expect(ask).toHaveTextContent("CTR lệch −5,2 % (ngưỡng ±3 %)");
    await waitFor(() => expect(screen.getByTestId("measure-panel")).toHaveTextContent("Đã đổi Mô tả"));
    await userEvent.click(within(ask).getByRole("button", { name: "Giữ thay đổi" }));
    await waitFor(() => expect(screen.queryByTestId("day7-ask")).toBeNull());
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
  });
});
