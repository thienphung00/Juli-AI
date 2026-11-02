import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { OpsMe, ShopProposalRow } from "../../../lib/ops/types";
import { OpsCycle } from "../cycle/ops-cycle";

/** ADR-118 "Chu kỳ": synthetic proposals only. */

const OPERATOR: OpsMe = { email: "op@example.test", role: "operator", role_label: "Vận hành" };
const VIEWER: OpsMe = { email: "v@example.test", role: "viewer", role_label: "Xem" };

function row(id: string, status: string, over: Partial<ShopProposalRow> = {}): ShopProposalRow {
  return {
    id,
    revision: 1,
    cycle: "Đợt A",
    kind: "price",
    subject_type: "shop",
    item_id: null,
    subject_label: `Đề xuất ${id}`,
    change_before: { text: "100" },
    change_after: { text: "90" },
    reason: "Lý do thử",
    planned_start: null,
    status,
    platform: "shopee",
    supersedes_id: null,
    sent_at: null,
    created_at: "2026-11-01T01:00:00Z",
    approvals: [],
    executions: [],
    ...over,
  };
}

const STATUSES: ReadonlyArray<[string, string]> = [
  ["draft", "Nháp"],
  ["sent", "Đã gửi, chờ duyệt"],
  ["approved", "Đã duyệt"],
  ["rejected", "Bị từ chối"],
  ["executed", "Đã thực hiện"],
  ["measured", "Đã đo kết quả"],
];

describe("Chu kỳ", () => {
  it("lists each proposal with its status", async () => {
    const proposals = vi.fn().mockResolvedValue({ proposals: STATUSES.map(([s]) => row(s, s)) });
    render(<OpsCycle api={{ proposals }} me={OPERATOR} shopId="s1" />);
    for (const [s, label] of STATUSES) {
      const card = await screen.findByTestId(`proposal-${s}`);
      expect(within(card).getByTestId("status")).toHaveTextContent(label);
    }
  });

  it("shows an empty state", async () => {
    render(<OpsCycle api={{ proposals: vi.fn().mockResolvedValue({ proposals: [] }) }} me={OPERATOR} shopId="s1" />);
    expect(await screen.findByText("Chưa có đề xuất nào cho shop này.")).toBeInTheDocument();
  });

  it("creates a proposal with the right payload and reloads", async () => {
    const proposals = vi.fn().mockResolvedValue({ proposals: [] });
    const createProposal = vi.fn().mockResolvedValue({ proposal: row("n", "draft") });
    render(<OpsCycle api={{ proposals, createProposal }} me={OPERATOR} shopId="s1" />);
    fireEvent.click(await screen.findByRole("button", { name: "+ Tạo đề xuất" }));
    fireEvent.change(screen.getByLabelText("Đợt"), { target: { value: " Đợt A " } });
    fireEvent.change(screen.getByLabelText("Đối tượng"), { target: { value: "item" } });
    fireEvent.change(screen.getByLabelText("Mã sản phẩm Shopee"), { target: { value: "555" } });
    fireEvent.change(screen.getByLabelText("Tên hiển thị"), { target: { value: "Mẫu A" } });
    fireEvent.change(screen.getByLabelText("Đề xuất đổi thành"), { target: { value: "90" } });
    fireEvent.change(screen.getByLabelText("Lý do (khách hàng đọc được)"), { target: { value: "Giá cạnh tranh" } });
    fireEvent.click(screen.getByRole("button", { name: "Lưu nháp" }));
    await waitFor(() => expect(createProposal).toHaveBeenCalled());
    expect(createProposal).toHaveBeenCalledWith("s1", {
      cycle: "Đợt A",
      kind: "price",
      subject_type: "item",
      item_id: "555",
      subject_label: "Mẫu A",
      change_before: {},
      change_after: { text: "90" },
      reason: "Giá cạnh tranh",
      planned_start: null,
    });
    await waitFor(() => expect(proposals).toHaveBeenCalledTimes(2));
  });

  it("records an approval with channel and evidence", async () => {
    const proposals = vi.fn().mockResolvedValue({ proposals: [row("p1", "sent")] });
    const recordApproval = vi.fn().mockResolvedValue({ proposal_id: "p1", status: "approved" });
    render(<OpsCycle api={{ proposals, recordApproval }} me={OPERATOR} shopId="s1" />);
    fireEvent.click(await screen.findByRole("button", { name: "Ghi quyết định của khách" }));
    fireEvent.change(screen.getByLabelText("Kênh"), { target: { value: "document" } });
    fireEvent.change(screen.getByLabelText("Nơi lưu bằng chứng"), { target: { value: "hop-dong-01.pdf" } });
    fireEvent.change(screen.getByLabelText("Khách quyết định lúc"), { target: { value: "2026-11-02T09:30" } });
    fireEvent.click(screen.getByRole("button", { name: "Lưu quyết định" }));
    await waitFor(() => expect(recordApproval).toHaveBeenCalled());
    const [shopId, pid, body] = recordApproval.mock.calls[0];
    expect([shopId, pid]).toEqual(["s1", "p1"]);
    expect(body).toMatchObject({ decision: "approved", channel: "document", evidence_ref: "hop-dong-01.pdf", note: null });
    expect(new Date(body.decided_at).getTime()).toBe(new Date("2026-11-02T09:30").getTime());
  });

  it("records an execution on an approved proposal", async () => {
    const proposals = vi.fn().mockResolvedValue({ proposals: [row("p1", "approved")] });
    const recordExecution = vi.fn().mockResolvedValue({});
    render(<OpsCycle api={{ proposals, recordExecution }} me={OPERATOR} shopId="s1" />);
    fireEvent.click(await screen.findByRole("button", { name: "Ghi việc đã thực hiện" }));
    fireEvent.change(screen.getByLabelText("Thực hiện lúc"), { target: { value: "2026-11-03T10:00" } });
    fireEvent.click(screen.getByRole("button", { name: "Lưu việc đã làm" }));
    await waitFor(() => expect(recordExecution).toHaveBeenCalled());
    expect(recordExecution.mock.calls[0][2]).toMatchObject({ executor_role: "client_representative", evidence_ref: null });
  });

  it("shows recorded decisions and executions", async () => {
    const proposals = vi.fn().mockResolvedValue({
      proposals: [
        row("p1", "executed", {
          approvals: [{ id: "a", decision: "approved", channel: "email", evidence_ref: "thu-01", note: null, decided_at: "2026-11-02T02:00:00Z" }],
          executions: [{ id: "e", executed_at: "2026-11-03T03:00:00Z", executor_role: "client_representative", channel: "ops", evidence_ref: null, verified_at: null, verified_how: null }],
        }),
      ],
    });
    render(<OpsCycle api={{ proposals }} me={OPERATOR} shopId="s1" />);
    expect(await screen.findByText(/Quyết định: Duyệt · Email · bằng chứng: thu-01/)).toBeInTheDocument();
    expect(screen.getByText(/Đã thực hiện: Đại diện khách hàng/)).toBeInTheDocument();
  });

  it("gives a viewer no forms or buttons", async () => {
    const api = {
      proposals: vi.fn().mockResolvedValue({ proposals: [row("a", "draft"), row("b", "sent"), row("c", "approved")] }),
      createProposal: vi.fn(),
      sendProposal: vi.fn(),
      recordApproval: vi.fn(),
      recordExecution: vi.fn(),
      withdrawProposal: vi.fn(),
    };
    render(<OpsCycle api={api} me={VIEWER} shopId="s1" />);
    await screen.findByTestId("proposal-a");
    expect(screen.queryByRole("button")).toBeNull();
  });
});
