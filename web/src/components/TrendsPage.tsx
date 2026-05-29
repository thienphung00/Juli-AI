"use client";

import { useCallback, useEffect, useState } from "react";
import { Search } from "lucide-react";
import { AuthenticatedShell } from "./AuthenticatedShell";
import { formatNumber, formatVND } from "@/lib/format";
import type { TrendsTab } from "@/lib/mock-data/trends";
import { useWorkspaceMode } from "@/lib/mode-context";
import { getTrends } from "@/lib/services/trends";
import type { TrendsResults } from "@/lib/mock-data/trends";

const TABS: { id: TrendsTab; label: string }[] = [
  { id: "product", label: "Sản phẩm" },
  { id: "creator", label: "Creator" },
  { id: "shop", label: "Shop" },
];

const SEARCH_DEBOUNCE_MS = 300;

function formatPct(value: number, digits = 1): string {
  return `${(value * 100).toFixed(digits).replace(".", ",")}%`;
}

function MarketIntelBanner() {
  return (
    <p
      className="rounded-lg border px-3 py-2 text-xs"
      data-testid="trends-market-intel-banner"
      style={{
        borderColor: "var(--border)",
        color: "var(--muted-foreground)",
        background: "var(--card)",
      }}
    >
      Đang cập nhật dữ liệu thị trường
    </p>
  );
}

function ProductTab({
  data,
  mode,
}: {
  data: TrendsResults;
  mode: "seller" | "affiliate";
}) {
  if (data.products.length === 0) {
    return (
      <p className="py-8 text-center text-sm" style={{ color: "var(--muted-foreground)" }}>
        Không tìm thấy sản phẩm phù hợp.
      </p>
    );
  }

  return (
    <div className="space-y-3" data-testid="trends-product-tab">
      {data.products.map((product) => (
        <article
          key={product.id}
          className="rounded-xl border p-4"
          data-testid="trends-product-card"
          style={{ borderColor: "var(--border)", background: "var(--card)" }}
        >
          <p className="text-xs font-medium" style={{ color: "var(--muted-foreground)" }}>
            🔥 #{product.rank}
          </p>
          <h3 className="mt-1 font-semibold">{product.name}</h3>
          <p className="text-sm" style={{ color: "var(--muted-foreground)" }}>
            {formatVND(product.price_vnd)} · +{product.growth_7d_pct}% lượt bán 7 ngày qua
          </p>
          {mode === "seller" ? (
            <p
              className="mt-2 text-sm"
              data-testid="trends-product-seller-fit"
            >
              Điểm creator phù hợp: {formatPct(product.seller_creator_fit_score, 0)}
            </p>
          ) : (
            <p
              className="mt-2 text-sm"
              data-testid="trends-product-affiliate-commission"
            >
              Hoa hồng: {product.commission_pct}%
            </p>
          )}
        </article>
      ))}
    </div>
  );
}

function CreatorTabSeller({ data }: { data: TrendsResults }) {
  return (
    <div className="space-y-3" data-testid="trends-creator-seller">
      <p className="text-xs font-medium" style={{ color: "var(--muted-foreground)" }}>
        Creator phù hợp nhất với shop bạn
      </p>
      {data.creatorsSeller.map((creator) => (
        <article
          key={creator.id}
          className="rounded-xl border p-4"
          data-testid="trends-creator-card"
          style={{ borderColor: "var(--border)", background: "var(--card)" }}
        >
          <h3 className="font-semibold">{creator.handle}</h3>
          <p className="text-sm" style={{ color: "var(--muted-foreground)" }}>
            {formatNumber(creator.followers)} followers · {creator.category}
          </p>
          <p className="mt-2 text-sm" data-testid="trends-creator-brand-fit">
            ✨ Điểm phù hợp thương hiệu: {formatPct(creator.brand_fit_score, 0)}
          </p>
          <p className="text-sm">
            Chuyển đổi TB: {formatPct(creator.avg_conversion_rate)} · Hoàn trả:{" "}
            {formatPct(creator.refund_rate)}
          </p>
          <p className="text-sm">Phong cách: {creator.content_style}</p>
        </article>
      ))}
    </div>
  );
}

function CreatorTabAffiliate({ data }: { data: TrendsResults }) {
  return (
    <div className="space-y-3" data-testid="trends-creator-affiliate">
      <p className="text-xs font-medium" style={{ color: "var(--muted-foreground)" }}>
        Creator đối thủ trong danh mục bạn
      </p>
      {data.creatorsAffiliate.map((creator) => (
        <article
          key={creator.id}
          className="rounded-xl border p-4"
          data-testid="trends-creator-card"
          style={{ borderColor: "var(--border)", background: "var(--card)" }}
        >
          <h3 className="font-semibold">{creator.handle}</h3>
          <p className="text-sm" style={{ color: "var(--muted-foreground)" }}>
            {formatNumber(creator.followers)} followers · {creator.category}
          </p>
          <p className="mt-2 text-sm" data-testid="trends-creator-gmv-growth">
            Tăng trưởng GMV: +{creator.gmv_growth_7d_pct}% tuần này
          </p>
          <p className="text-sm">
            Sản phẩm đang đẩy: {creator.products_currently_promoting.join(", ")}
          </p>
          <p className="text-sm">Format: {creator.content_format}</p>
          <p className="text-sm" data-testid="trends-creator-audience-overlap">
            Trùng audience với bạn: {creator.audience_overlap_pct}%
          </p>
        </article>
      ))}
    </div>
  );
}

function ShopTabSeller({ data }: { data: TrendsResults }) {
  return (
    <div className="space-y-3" data-testid="trends-shop-seller">
      <p className="text-xs font-medium" style={{ color: "var(--muted-foreground)" }}>
        Shop đối thủ trong danh mục bạn
      </p>
      {data.shopsSeller.map((shop) => (
        <article
          key={shop.id}
          className="rounded-xl border p-4"
          data-testid="trends-shop-card"
          style={{ borderColor: "var(--border)", background: "var(--card)" }}
        >
          <h3 className="font-semibold">🏪 {shop.name}</h3>
          <p className="text-sm" style={{ color: "var(--muted-foreground)" }}>
            {shop.rating}★ · {formatNumber(shop.followers)} followers · {shop.category}
          </p>
          <p className="mt-2 text-sm" data-testid="trends-shop-network-size">
            Số creator hợp tác: ~{shop.creator_network_size}
          </p>
          <p className="text-sm">Hoa hồng đang trả: {shop.commission_range_pct}</p>
          <p className="text-sm">Sản phẩm bán chạy: {shop.top_product}</p>
          {shop.commission_delta_alert ? (
            <p className="text-sm" data-testid="trends-shop-commission-alert">
              ⚠️ Tăng hoa hồng {shop.commission_delta_alert}
            </p>
          ) : null}
        </article>
      ))}
    </div>
  );
}

function ShopTabAffiliate({ data }: { data: TrendsResults }) {
  return (
    <div className="space-y-3" data-testid="trends-shop-affiliate">
      <p className="text-xs font-medium" style={{ color: "var(--muted-foreground)" }}>
        Shop phù hợp nhất với bạn
      </p>
      {data.shopsAffiliate.map((shop) => (
        <article
          key={shop.id}
          className="rounded-xl border p-4"
          data-testid="trends-shop-card"
          style={{ borderColor: "var(--border)", background: "var(--card)" }}
        >
          <h3 className="font-semibold">🤝 {shop.name}</h3>
          <p className="text-sm" style={{ color: "var(--muted-foreground)" }}>
            {shop.rating}★ · {formatNumber(shop.followers)} followers · {shop.category}
          </p>
          <p className="mt-2 text-sm" data-testid="trends-shop-audience-fit">
            ✨ Độ phù hợp với audience: {formatPct(shop.audience_fit_score, 0)}
          </p>
          <p className="text-sm">
            Hoa hồng: {shop.commission_range} · TB: {shop.avg_commission_pct}%
          </p>
          <p className="text-sm">
            Chấp nhận creator mới: {shop.accepts_new_affiliates ? "✓ Có" : "Không"}
          </p>
          <p className="text-sm">Thời gian duyệt mẫu: ~{shop.sample_approval_days} ngày</p>
        </article>
      ))}
    </div>
  );
}

export function TrendsPage() {
  const { mode } = useWorkspaceMode();
  const [activeTab, setActiveTab] = useState<TrendsTab>("product");
  const [searchInput, setSearchInput] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [results, setResults] = useState<TrendsResults | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setDebouncedQuery(searchInput);
    }, SEARCH_DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [searchInput]);

  const loadTrends = useCallback(async () => {
    if (!mode) return;
    setLoading(true);
    try {
      const data = await getTrends({
        mode,
        tab: activeTab,
        query: debouncedQuery,
      });
      setResults(data);
    } catch (error) {
      console.error("trends_load_failed", { error });
    } finally {
      setLoading(false);
    }
  }, [mode, activeTab, debouncedQuery]);

  useEffect(() => {
    loadTrends();
  }, [loadTrends]);

  return (
    <AuthenticatedShell title="Xu hướng">
      <div className="space-y-4" data-testid="trends-page">
        <label className="relative block">
          <Search
            className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2"
            style={{ color: "var(--muted-foreground)" }}
            aria-hidden
          />
          <input
            type="search"
            value={searchInput}
            onChange={(event) => setSearchInput(event.target.value)}
            placeholder="Tìm sản phẩm, creator, shop..."
            className="w-full rounded-xl border py-2.5 pl-10 pr-3 text-sm outline-none"
            data-testid="trends-search-input"
            style={{
              borderColor: "var(--border)",
              background: "var(--card)",
              color: "var(--foreground)",
            }}
          />
        </label>

        <div
          className="flex gap-1 rounded-xl p-1"
          role="tablist"
          data-testid="trends-tabs"
          style={{ background: "var(--muted)" }}
        >
          {TABS.map((tab) => (
            <button
              key={tab.id}
              type="button"
              role="tab"
              aria-selected={activeTab === tab.id}
              onClick={() => setActiveTab(tab.id)}
              className="flex-1 rounded-lg px-2 py-2 text-sm font-medium transition-colors"
              data-testid={`trends-tab-${tab.id}`}
              style={{
                background: activeTab === tab.id ? "var(--card)" : "transparent",
                color:
                  activeTab === tab.id
                    ? "var(--foreground)"
                    : "var(--muted-foreground)",
              }}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {loading || !results || !mode ? (
          <div className="flex justify-center py-12">
            <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary-500 border-t-transparent" />
          </div>
        ) : (
          <div role="tabpanel" data-testid={`trends-panel-${activeTab}`}>
            {(activeTab === "creator" || activeTab === "shop") && (
              <div className="mb-3">
                <MarketIntelBanner />
              </div>
            )}
            {activeTab === "product" ? (
              <ProductTab data={results} mode={mode} />
            ) : activeTab === "creator" ? (
              mode === "seller" ? (
                <CreatorTabSeller data={results} />
              ) : (
                <CreatorTabAffiliate data={results} />
              )
            ) : mode === "seller" ? (
              <ShopTabSeller data={results} />
            ) : (
              <ShopTabAffiliate data={results} />
            )}
          </div>
        )}
      </div>
    </AuthenticatedShell>
  );
}
