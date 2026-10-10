import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { uploadVideo } from "../../lib/content-analysis/api-client";
import { SAMPLE_ANALYSES, createSampleAnalysisClients } from "../../lib/content-analysis/sample";
import { checkFile, contentTypeOf, type ContentAnalysis, type ContentAnalysisClients } from "../../lib/content-analysis/types";
import { VideoAnalysis } from "../content-analysis/video-analysis";

/**
 * P15 "Phân tích video" (`fasttrack/contracts/p15-content-analysis.md` §5):
 * the sample's canned analysis (no network, upload disabled), the client-side
 * file checks, upload → queued → polled → done, refused / failed messages, and
 * the chunked upload client resuming at the server's offset.
 */

afterEach(() => {
  vi.useRealTimers();
});

const DONE = SAMPLE_ANALYSES.video;

function analysis(overrides: Partial<ContentAnalysis>): ContentAnalysis {
  return { ...DONE, id: "a-1", result: null, status: "queued", status_label: "Đang chờ phân tích", ...overrides };
}

function fakeClients(overrides: Partial<ContentAnalysisClients> = {}): ContentAnalysisClients {
  return {
    sample: false,
    list: vi.fn(async () => []),
    get: vi.fn(async () => DONE),
    upload: vi.fn(async () => analysis({})),
    ...overrides,
  };
}

describe("VideoAnalysis", () => {
  it("shows the sample's canned analysis and disables the upload", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    render(<VideoAnalysis clients={createSampleAnalysisClients()} target={{ kind: "video" }} />);
    expect(await screen.findByTestId("video-analysis-result")).toBeInTheDocument();
    for (const label of ["Hook (3 giây đầu)", "Giây sản phẩm xuất hiện", "Lời kêu gọi mua (CTA)", "Nhịp cắt", "Vấn đề", "Gợi ý"]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
    expect(screen.getByText("Sản phẩm xuất hiện lần đầu ở giây 6,0")).toBeInTheDocument();
    expect(screen.getByText("Bản minh họa")).toBeInTheDocument();
    expect(screen.getByTestId("video-analysis-input")).toBeDisabled();
    expect(fetchSpy).not.toHaveBeenCalled();
    fetchSpy.mockRestore();
  });

  it("shows the LIVE windows' hook label for a LIVE", async () => {
    render(<VideoAnalysis clients={createSampleAnalysisClients()} target={{ kind: "live" }} />);
    expect(await screen.findByText("Hook (30 giây đầu khi nói về sản phẩm)")).toBeInTheDocument();
    expect(screen.getByText("Sản phẩm xuất hiện lần đầu ở 21:02")).toBeInTheDocument();
  });

  it("refuses a wrong type before sending anything", async () => {
    const clients = fakeClients();
    render(<VideoAnalysis clients={clients} target={{ kind: "video", contentRef: "video:1", productId: "p" }} />);
    await screen.findByText(/Tải video của bạn lên/);
    const input = screen.getByTestId("video-analysis-input");
    await userEvent.upload(input, new File(["x"], "clip.avi", { type: "video/x-msvideo" }), { applyAccept: false });
    expect(await screen.findByRole("alert")).toHaveTextContent("Juli chỉ nhận video MP4 hoặc MOV.");
    expect(clients.upload).not.toHaveBeenCalled();
  });

  it("uploads, then polls the queued analysis until it is done", async () => {
    let resolveUpload: (value: ContentAnalysis) => void = () => undefined;
    const clients = fakeClients({
      upload: vi.fn(
        (_target, _file, onProgress) =>
          new Promise<ContentAnalysis>((resolve) => {
            onProgress?.(0.5);
            resolveUpload = resolve;
          }),
      ),
      get: vi.fn(async () => DONE),
    });
    render(<VideoAnalysis clients={clients} target={{ kind: "video", contentRef: "video:1", productId: "p" }} />);
    await screen.findByText(/Tải video của bạn lên/);
    await userEvent.upload(screen.getByTestId("video-analysis-input"), new File(["abc"], "clip.mp4", { type: "video/mp4" }));
    expect(await screen.findByText("Đang tải lên… 50 %")).toBeInTheDocument();
    expect(clients.upload).toHaveBeenCalledWith({ kind: "video", contentRef: "video:1", productId: "p" }, expect.any(File), expect.any(Function));
    vi.useFakeTimers({ shouldAdvanceTime: true });
    await act(async () => resolveUpload(analysis({})));
    expect(await screen.findByText("Video đã tải lên, đang chờ Juli phân tích…")).toBeInTheDocument();
    await act(async () => {
      vi.advanceTimersByTime(5_100);
    });
    await waitFor(() => expect(screen.getByTestId("video-analysis-result")).toBeInTheDocument());
    expect(screen.getByTestId("video-analysis-status")).toHaveTextContent("Đã phân tích");
  });

  it("shows the backend's Vietnamese reason for a refused analysis", async () => {
    const refused = analysis({
      status: "refused",
      status_label: "Đã đạt hạn mức tháng",
      error: { code: "cost_cap_reached", message: "Shop đã dùng hết hạn mức phân tích bằng AI của tháng này." },
    });
    render(<VideoAnalysis clients={fakeClients({ list: vi.fn(async () => [refused]) })} target={{ kind: "video", runId: "r" }} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("hết hạn mức");
    expect(screen.getByTestId("video-analysis-status")).toHaveTextContent("Đã đạt hạn mức tháng");
  });
});

describe("content-analysis client", () => {
  it("checks type and size like the backend", () => {
    expect(checkFile("video", { name: "a.mp4", type: "video/mp4", size: 10 })).toBeNull();
    expect(checkFile("video", { name: "a.MOV", type: "", size: 10 })).toBeNull();
    expect(checkFile("video", { name: "a.mp4", type: "video/mp4", size: 501 * 1024 * 1024 })).toMatch(/500 MB/);
    expect(checkFile("live", { name: "a.mp4", type: "video/mp4", size: 900 * 1024 * 1024 })).toBeNull();
    expect(contentTypeOf({ name: "a.mov", type: "" })).toBe("video/quicktime");
  });

  it("uploads in chunks and resumes at the server's expected offset", async () => {
    const calls: string[] = [];
    let held = 0;
    let lostOnce = false;
    const fetchImpl = vi.fn(async (url: string, init?: RequestInit) => {
      calls.push(`${init?.method ?? "GET"} ${url}`);
      if (init?.method === "POST") {
        return Response.json(
          { data: { analysis: analysis({ status: "awaiting_upload" }), upload: { url: "/v1/demo/content-analysis/a-1/file", token: "t.k", chunk_bytes: 4, expires_at: "" } } },
          { status: 201 },
        );
      }
      const offset = Number(new URL(url, "http://x").searchParams.get("offset"));
      const size = (init?.body as Blob).size;
      if (offset !== held) {
        return Response.json({ detail: { code: "offset_mismatch", message: "x", expected_offset: held } }, { status: 409 });
      }
      held += size;
      if (held === 8 && !lostOnce) {
        // The answer to the 2nd chunk is lost: the client resends it.
        lostOnce = true;
        return new Response("bad gateway", { status: 502 });
      }
      const status = held === 10 ? "queued" : "awaiting_upload";
      return Response.json({ data: analysis({ status, upload: { received_bytes: held, size_bytes: 10 } }) });
    });
    const progress: number[] = [];
    const out = await uploadVideo(
      { token: "tok", shopId: "shop", fetchImpl: fetchImpl as unknown as typeof fetch },
      { kind: "video", contentRef: "video:1", productId: "p" },
      new File(["0123456789"], "clip.mp4", { type: "video/mp4" }),
      (f) => progress.push(f),
    );
    expect(out.status).toBe("queued");
    expect(held).toBe(10);
    expect(calls[0]).toBe("POST /v1/demo/content-analysis");
    expect(calls).toContain("PUT /v1/demo/content-analysis/a-1/file?offset=4");
    expect(progress.at(-1)).toBe(1);
    const headers = fetchImpl.mock.calls[1][1]?.headers as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer tok");
    expect(headers["X-Shop-Id"]).toBe("shop");
    expect(headers["X-Upload-Token"]).toBe("t.k");
    expect(calls.join(" ")).not.toContain("token=");
  });
});
