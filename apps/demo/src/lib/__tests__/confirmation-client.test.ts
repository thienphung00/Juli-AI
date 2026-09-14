import { describe, expect, it, vi } from "vitest";

import { submitConfirmationDecision } from "../run-surface/confirmation-client";

describe("submitConfirmationDecision — X-Shop-Id joins the bearer token (#1909)", () => {
  it("sends X-Shop-Id when the caller supplies the acting shop", async () => {
    const fetchImpl = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ decision: "approve", status: "running", celery_task_id: "t-1" }),
    } as Response);

    await submitConfirmationDecision("run-1", "call-1", "approve", "opt-1", {
      token: "bearer-1",
      shopId: "shop-1",
      fetchImpl,
    });

    const [, init] = fetchImpl.mock.calls[0] as [string, RequestInit];
    const headers = new Headers(init.headers);
    expect(headers.get("Authorization")).toBe("Bearer bearer-1");
    expect(headers.get("X-Shop-Id")).toBe("shop-1");
  });
});
