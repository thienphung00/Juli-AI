"use client";

import { useCallback, useEffect, useState } from "react";
import { api, type Product, type ProductsResponse, ApiError } from "@/lib/api-client";
import { formatVND, formatNumber } from "@/lib/format";
import { NavBar } from "./NavBar";

export function ProductsPage() {
  const [products, setProducts] = useState<Product[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadProducts = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data: ProductsResponse = await api.products.list();
      setProducts(data.products);
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setProducts([]);
      } else {
        setError("Không thể tải sản phẩm. Vui lòng thử lại.");
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadProducts();
  }, [loadProducts]);

  return (
    <div className="min-h-screen pb-24" style={{ background: "var(--background)" }}>
      <header
        className="sticky top-0 z-10 px-4 py-3"
        style={{ background: "var(--background)", borderBottom: "1px solid var(--border)" }}
      >
        <div className="mx-auto max-w-lg">
          <h1 className="text-lg font-bold">Xu hướng</h1>
        </div>
      </header>

      <main className="mx-auto max-w-lg px-4 pt-4">
        {error && (
          <p role="alert" className="mb-4 rounded-xl p-3 text-sm" style={{ background: "#ef444420", color: "#ef4444" }}>
            {error}
          </p>
        )}

        {loading ? (
          <div className="flex justify-center py-12">
            <span className="spinner" />
          </div>
        ) : products.length === 0 ? (
          <div className="py-12 text-center" data-testid="products-empty">
            <p className="text-lg font-medium" style={{ color: "var(--muted-foreground)" }}>Chưa có sản phẩm nào</p>
            <p className="mt-1 text-sm" style={{ color: "var(--muted-foreground)", opacity: 0.6 }}>
              Sản phẩm sẽ hiển thị khi có dữ liệu từ TikTok Shop
            </p>
          </div>
        ) : (
          <div className="space-y-3" data-testid="products-list">
            <p className="text-xs" style={{ color: "var(--muted-foreground)" }}>
              {formatNumber(products.length)} sản phẩm • Xếp theo doanh thu
            </p>
            {products.map((product, idx) => (
              <ProductCard key={product.id} product={product} rank={idx + 1} />
            ))}
          </div>
        )}
      </main>

      <NavBar />
    </div>
  );
}

function ProductCard({ product, rank }: { product: Product; rank: number }) {
  return (
    <div className="card p-4" data-testid="product-card">
      <div className="flex items-start gap-3">
        <span
          className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full text-sm font-bold"
          style={{ background: "var(--muted)", color: "var(--muted-foreground)" }}
        >
          {rank}
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium">{product.name}</p>
          <p className="mt-0.5 text-xs" style={{ color: "var(--muted-foreground)" }}>{product.sku}</p>
        </div>
        <VelocityIndicator trend={product.velocity_trend} velocity={product.velocity} />
      </div>

      <div className="mt-3 flex items-center justify-between pt-3" style={{ borderTop: "1px solid var(--border)" }}>
        <div>
          <p className="text-xs" style={{ color: "var(--muted-foreground)" }}>Doanh thu</p>
          <p className="text-sm font-semibold">{formatVND(product.revenue)}</p>
        </div>
        <div className="text-right">
          <p className="text-xs" style={{ color: "var(--muted-foreground)" }}>Đã bán</p>
          <p className="text-sm font-medium">{formatNumber(product.units_sold)}</p>
        </div>
      </div>
    </div>
  );
}

function VelocityIndicator({
  trend,
  velocity,
}: {
  trend: Product["velocity_trend"];
  velocity: number;
}) {
  const config: Record<string, { icon: string; bg: string; color: string; testId: string }> = {
    accelerating: { icon: "↑", bg: "#10b98120", color: "#10b981", testId: "velocity-accelerating" },
    decelerating: { icon: "↓", bg: "#ef444420", color: "#ef4444", testId: "velocity-decelerating" },
    stable:       { icon: "→", bg: "var(--muted)", color: "var(--muted-foreground)", testId: "velocity-stable" },
  };

  const { icon, bg, color, testId } = config[trend];

  return (
    <span
      className="badge"
      style={{ background: bg, color }}
      data-testid={testId}
    >
      {icon} {velocity.toFixed(1)}/ngày
    </span>
  );
}
