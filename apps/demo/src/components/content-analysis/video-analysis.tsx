"use client";

import { useEffect, useId, useRef, useState } from "react";

import {
  ACCEPT,
  checkFile,
  isWorking,
  type AnalysisResult,
  type AnalysisTarget,
  type ContentAnalysis,
  type ContentAnalysisClients,
} from "../../lib/content-analysis/types";

/**
 * P15 "Phân tích video" (contract `p15-content-analysis.md` §5). NO ARTBOARD
 * EXISTS for this block: it reuses the ContentRun / Phân tích boxes and is a
 * deviation awaiting owner review (fasttrack/DEBT.md). It shows the latest
 * analysis for the target (a Phân tích row or a content run) — hook, giây sản
 * phẩm xuất hiện, CTA, nhịp cắt, vấn đề, gợi ý — and an upload control. While
 * an analysis is queued / running the block polls every 5 s. The sample door
 * passes sample clients: a canned analysis and a disabled upload, no network.
 */

const POLL_MS = 5_000;

function errorText(error: unknown, fallback: string): string {
  return error instanceof Error && error.message && !error.message.startsWith("Request failed") ? error.message : fallback;
}

export function AnalysisResultView({ result }: { readonly result: AnalysisResult }) {
  return (
    <div className="qv-va__result" data-testid="video-analysis-result">
      <dl className="qv-va__facts">
        <div className="qv-va__fact">
          <dt>Hook {result.kind === "live" ? "(30 giây đầu khi nói về sản phẩm)" : "(3 giây đầu)"}</dt>
          <dd>
            <span className={`qv-va__verdict qv-va__verdict--${result.hook.verdict ?? "none"}`}>{result.hook.label}</span>
            {result.hook.reason ? ` · ${result.hook.reason}` : null}
          </dd>
        </div>
        <div className="qv-va__fact">
          <dt>Giây sản phẩm xuất hiện</dt>
          <dd>{result.product_line}</dd>
        </div>
        <div className="qv-va__fact">
          <dt>Lời kêu gọi mua (CTA)</dt>
          <dd>
            {result.cta.line}
            {result.cta.text ? ` · “${result.cta.text}”` : null}
          </dd>
        </div>
        <div className="qv-va__fact">
          <dt>Nhịp cắt</dt>
          <dd>{result.pacing.line}</dd>
        </div>
      </dl>
      {result.issues.length > 0 ? (
        <div className="qv-va__list">
          <span className="qv-va__k">Vấn đề</span>
          <ul>
            {result.issues.map((issue) => (
              <li key={`${issue.code}-${issue.text}`}>{issue.text}</li>
            ))}
          </ul>
        </div>
      ) : null}
      {result.suggestions.length > 0 ? (
        <div className="qv-va__list">
          <span className="qv-va__k">Gợi ý</span>
          <ul>
            {result.suggestions.map((text) => (
              <li key={text}>{text}</li>
            ))}
          </ul>
        </div>
      ) : null}
      <p className="qv-va__note">
        Juli chỉ giữ kết quả phân tích; tệp video đã được xoá. Kịch bản Juli soạn cho sản phẩm này sẽ dựa trên các phân tích này.
      </p>
    </div>
  );
}

export interface VideoAnalysisProps {
  readonly clients: ContentAnalysisClients;
  readonly target: AnalysisTarget;
  /** Heading level context: inside a row detail the block is compact. */
  readonly compact?: boolean;
}

export function VideoAnalysis({ clients, target, compact = false }: VideoAnalysisProps) {
  const inputId = useId();
  const headingId = useId();
  const [latest, setLatest] = useState<ContentAnalysis | null>(null);
  const [loading, setLoading] = useState(true);
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const { kind, contentRef, productId, runId } = target;

  useEffect(() => {
    let cancelled = false;
    clients
      .list({ kind, contentRef, productId, runId })
      .then((list) => {
        if (!cancelled) setLatest(list[0] ?? null);
      })
      .catch(() => {
        if (!cancelled) setError("Chưa tải được phân tích video. Vui lòng thử lại.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [clients, kind, contentRef, productId, runId]);

  const working = latest !== null && isWorking(latest.status) && progress === null;
  useEffect(() => {
    if (!working || !latest) return;
    const timer = window.setInterval(() => {
      clients
        .get(latest.id)
        .then(setLatest)
        .catch(() => undefined);
    }, POLL_MS);
    return () => window.clearInterval(timer);
  }, [working, latest, clients]);

  const onFile = (file: File | undefined) => {
    if (!file) return;
    const problem = checkFile(kind, file);
    if (problem) {
      setError(problem);
      return;
    }
    setError(null);
    setProgress(0);
    clients
      .upload(target, file, (fraction) => setProgress(fraction))
      .then((analysis) => setLatest(analysis))
      .catch((reason: unknown) => setError(errorText(reason, "Chưa tải lên được. Vui lòng thử lại.")))
      .finally(() => {
        setProgress(null);
        if (inputRef.current) inputRef.current.value = "";
      });
  };

  const what = kind === "live" ? "bản ghi LIVE" : "video";
  const limits = kind === "live" ? "MP4 / MOV, tối đa 3 giờ" : "MP4 / MOV, tối đa 500 MB, 10 phút";
  const uploading = progress !== null;
  return (
    <section aria-labelledby={headingId} className={`qv-va${compact ? " qv-va--compact" : ""}`} data-testid="video-analysis">
      <div className="qv-va__head">
        <h3 className="qv-va__title" id={headingId}>
          Phân tích video
        </h3>
        {clients.sample ? <span className="qv-va__badge">Bản minh họa</span> : null}
        {latest && !uploading ? (
          <span className="qv-va__status" data-status={latest.status} data-testid="video-analysis-status">
            {latest.status_label}
          </span>
        ) : null}
      </div>

      {loading ? (
        <p className="qv-va__muted" role="status">
          Đang tải…
        </p>
      ) : null}

      {latest?.status === "done" && latest.result && !uploading ? <AnalysisResultView result={latest.result} /> : null}
      {latest && working ? (
        <p className="qv-va__muted" role="status">
          {latest.status === "processing" ? "Juli đang xem lời thoại, chữ trên màn hình và nhịp cắt…" : "Video đã tải lên, đang chờ Juli phân tích…"}
        </p>
      ) : null}
      {latest?.error && !uploading && !isWorking(latest.status) ? (
        <p className="qv-inline-error" role="alert">
          {latest.error.message}
        </p>
      ) : null}
      {!loading && !latest && !uploading ? (
        <p className="qv-va__muted">Tải {what} của bạn lên để Juli xem hook, giây sản phẩm xuất hiện, lời kêu gọi mua và nhịp cắt.</p>
      ) : null}

      {uploading ? (
        <div className="qv-va__progress" role="status">
          <span>Đang tải lên… {Math.round((progress ?? 0) * 100)} %</span>
          <progress max={1} value={progress ?? 0} />
        </div>
      ) : null}
      {error ? (
        <p className="qv-inline-error" role="alert">
          {error}
        </p>
      ) : null}

      <div className="qv-va__upload">
        <label className={`qv-btn qv-btn--secondary qv-va__pick${clients.sample || uploading || working ? " qv-va__pick--off" : ""}`} htmlFor={inputId}>
          {latest ? `Tải ${what} khác` : `Tải ${what} lên`}
        </label>
        <input
          accept={ACCEPT}
          aria-label={`Chọn ${what} để phân tích`}
          className="qv-va__input"
          data-testid="video-analysis-input"
          disabled={clients.sample || uploading || working}
          id={inputId}
          onChange={(event) => onFile(event.target.files?.[0])}
          ref={inputRef}
          type="file"
        />
        <span className="qv-va__hint">
          {clients.sample ? "Bản minh họa: đăng nhập và kết nối shop để tải video lên." : `${limits}. Juli xoá tệp ngay sau khi phân tích.`}
        </span>
      </div>
    </section>
  );
}
