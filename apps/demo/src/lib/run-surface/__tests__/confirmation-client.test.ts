import { describe, expect, it, vi } from "vitest";

import {
  CONFIRMATION_API_DEFAULT_BASE_URL,
  ConfirmationRejectedError,
  buildConfirmationDecisionUrl,
  submitConfirmationDecision,
} from "../confirmation-client";

function jsonResponse(body: unknown, ok = true, status = 200): Response {
  return { ok, status, statusText: "", json: async () => body } as Response;
}

describe("buildConfirmationDecisionUrl", () => {
  it("matches the backend route shape exactly, run id and tool call id URL-encoded", () => {
    expect(buildConfirmationDecisionUrl("run 1", "call/2")).toBe(
      `${CONFIRMATION_API_DEFAULT_BASE_URL}/runs/run%201/confirmations/call%2F2`,
    );
  });
});

describe("submitConfirmationDecision -- approve", () => {
  it("POSTs the selected option's id and the run's tool_call_id on the outbound request", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      jsonResponse({ decision: "approve", status: "approved", celery_task_id: "task-1" }),
    );

    await submitConfirmationDecision("run-1", "call-2", "approve", "option-b", {
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });

    expect(fetchImpl).toHaveBeenCalledTimes(1);
    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe("/v1/demo/runs/run-1/confirmations/call-2");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({ decision: "approve", option_id: "option-b" });
  });

  it("sends the bearer token in a header, never the URL", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      jsonResponse({ decision: "approve", status: "approved", celery_task_id: "task-1" }),
    );

    await submitConfirmationDecision("run-1", "call-2", "approve", "option-a", {
      token: "secret-token",
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });

    const [url, init] = fetchImpl.mock.calls[0];
    const headers = init.headers as Headers;
    expect(url).not.toContain("secret-token");
    expect(headers.get("Authorization")).toBe("Bearer secret-token");
  });

  it("refuses locally, sending no request, when approve has no optionId", async () => {
    const fetchImpl = vi.fn();

    await expect(
      submitConfirmationDecision("run-1", "call-2", "approve", null, {
        fetchImpl: fetchImpl as unknown as typeof fetch,
      }),
    ).rejects.toThrow(ConfirmationRejectedError);
    expect(fetchImpl).not.toHaveBeenCalled();
  });
});

describe("submitConfirmationDecision -- decline", () => {
  it("POSTs decision=decline with a null option_id", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      jsonResponse({ decision: "decline", status: "declined", celery_task_id: "task-2" }),
    );

    await submitConfirmationDecision("run-1", "call-2", "decline", null, {
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });

    const [, init] = fetchImpl.mock.calls[0];
    expect(JSON.parse(init.body as string)).toEqual({ decision: "decline", option_id: null });
  });
});

describe("submitConfirmationDecision -- rejection ladder", () => {
  it("carries the distinct error_code for a params_sha mismatch", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      jsonResponse(
        { detail: { message: "mismatch", error_code: "params_sha_mismatch" } },
        false,
        409,
      ),
    );

    await expect(
      submitConfirmationDecision("run-1", "call-2", "approve", "option-a", {
        fetchImpl: fetchImpl as unknown as typeof fetch,
      }),
    ).rejects.toMatchObject({ errorCode: "params_sha_mismatch", status: 409 });
  });

  it("carries the distinct error_code for already-decided", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      jsonResponse(
        { detail: { message: "already decided", error_code: "confirmation_already_decided" } },
        false,
        409,
      ),
    );

    await expect(
      submitConfirmationDecision("run-1", "call-2", "approve", "option-a", {
        fetchImpl: fetchImpl as unknown as typeof fetch,
      }),
    ).rejects.toMatchObject({ errorCode: "confirmation_already_decided" });
  });

  it("carries the distinct error_code for not-awaiting", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      jsonResponse(
        { detail: { message: "not awaiting", error_code: "run_not_awaiting_confirmation" } },
        false,
        409,
      ),
    );

    await expect(
      submitConfirmationDecision("run-1", "call-2", "approve", "option-a", {
        fetchImpl: fetchImpl as unknown as typeof fetch,
      }),
    ).rejects.toMatchObject({ errorCode: "run_not_awaiting_confirmation" });
  });

  it("still raises honestly on a plain-string detail (e.g. the rate limiter's 429)", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      jsonResponse({ detail: "Too many confirmation decisions for this shop; retry in 5s" }, false, 429),
    );

    await expect(
      submitConfirmationDecision("run-1", "call-2", "approve", "option-a", {
        fetchImpl: fetchImpl as unknown as typeof fetch,
      }),
    ).rejects.toMatchObject({ errorCode: null, status: 429 });
  });
});
