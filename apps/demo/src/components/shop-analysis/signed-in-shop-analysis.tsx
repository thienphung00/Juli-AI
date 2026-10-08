"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { fetchShopAnalysis } from "../../lib/shop-analysis/api-client";
import type { HeroRanking, ShopAnalysisEnvelope } from "../../lib/shop-analysis/types";
import { readActiveShop } from "../../lib/shop-session";
import { ShopAnalysisView } from "./shop-analysis-view";

/**
 * The SIGNED-IN Phân tích branch (AC-7.7): the acting shop's latest report,
 * read with the seller's bearer token + `X-Shop-Id`. A missing report (404)
 * is an honest empty state; a failure is an honest error with a retry —
 * never the synthetic sample standing in for the seller's shop.
 */

type LoadState =
  | { status: "loading" }
  | { status: "error" }
  | { status: "empty" }
  | { status: "ready"; envelope: ShopAnalysisEnvelope };

interface SignedInShopAnalysisProps {
  readonly token: string;
  /** Injectable for tests; defaults to the real authenticated client. */
  readonly loadAnalysis?: typeof fetchShopAnalysis;
}

export function SignedInShopAnalysis({
  token,
  loadAnalysis = fetchShopAnalysis,
}: SignedInShopAnalysisProps) {
  const [activeShop] = useState(() => readActiveShop());
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [reloadKey, setReloadKey] = useState(0);
  const [ranking, setRanking] = useState<HeroRanking>("60d");

  useEffect(() => {
    if (!activeShop) return;
    let cancelled = false;
    loadAnalysis({ token, shopId: activeShop.id, ranking })
      .then((envelope) => {
        if (cancelled) return;
        setState(envelope ? { status: "ready", envelope } : { status: "empty" });
      })
      .catch(() => {
        if (!cancelled) setState({ status: "error" });
      });
    return () => {
      cancelled = true;
    };
    // activeShop is resolved once per mount; reloadKey drives the retry.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, reloadKey, ranking]);

  if (!activeShop) {
    return (
      <section aria-labelledby="analytics-title" className="analysis-page">
        <h1 className="demo-title" id="analytics-title">
          Phân tích
        </h1>
        <div className="card analysis-empty" role="status">
          <p>Bạn chưa chọn shop đang thao tác. Mở Kết nối TikTok Shop để chọn shop.</p>
          <Link className="btn-secondary" href="/auth/connect-shop">
            Kết nối TikTok Shop
          </Link>
        </div>
      </section>
    );
  }

  if (state.status === "ready") {
    return (
      <ShopAnalysisView
        envelope={state.envelope}
        ranking={ranking}
        onRankingChange={(next) => {
          if (next === ranking) return;
          setState({ status: "loading" });
          setRanking(next);
        }}
      />
    );
  }

  return (
    <section aria-labelledby="analytics-title" className="analysis-page">
      <h1 className="demo-title" id="analytics-title">
        Phân tích
      </h1>
      <p className="analysis-header__shop">{activeShop.name}</p>
      {state.status === "loading" && (
        <p role="status" aria-live="polite" className="text-muted">
          Đang tải báo cáo của shop…
        </p>
      )}
      {state.status === "empty" && (
        <div className="card analysis-empty" role="status">
          <p className="analysis-eyebrow">Chưa có báo cáo</p>
          <p>
            Juli đang thu thập dữ liệu shop của bạn. Báo cáo phân tích đầu tiên sẽ xuất hiện sau khi
            có đủ số liệu, và được cập nhật mỗi ngày.
          </p>
        </div>
      )}
      {state.status === "error" && (
        <div className="card analysis-empty" role="alert">
          <p className="analysis-eyebrow">Chưa thể tải nội dung</p>
          <p>Không thể tải báo cáo phân tích cho shop của bạn. Vui lòng thử lại.</p>
          <button
            className="btn-secondary"
            type="button"
            onClick={() => {
              setState({ status: "loading" });
              setReloadKey((key) => key + 1);
            }}
          >
            Thử lại
          </button>
        </div>
      )}
    </section>
  );
}
