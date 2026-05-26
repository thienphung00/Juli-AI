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
    <div className="min-h-screen pb-20">
      <header className="sticky top-0 z-10 border-b bg-white px-4 py-3">
        <div className="mx-auto max-w-lg">
          <h1 className="text-lg font-bold">Sản phẩm</h1>
        </div>
      </header>

      <main className="mx-auto max-w-lg px-4 pt-4">
        {error && (
          <p role="alert" className="mb-4 text-sm text-red-600">
            {error}
          </p>
        )}

        {loading ? (
          <div className="flex justify-center py-12">
            <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary-500 border-t-transparent" />
          </div>
        ) : products.length === 0 ? (
          <div className="py-12 text-center" data-testid="products-empty">
            <p className="text-lg text-gray-400">Chưa có sản phẩm nào</p>
            <p className="mt-1 text-sm text-gray-300">
              Sản phẩm sẽ hiển thị khi có dữ liệu từ TikTok Shop
            </p>
          </div>
        ) : (
          <div className="space-y-3" data-testid="products-list">
            <p className="text-xs text-gray-500">
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
    <div className="rounded-xl bg-white p-4 shadow-sm" data-testid="product-card">
      <div className="flex items-start gap-3">
        <span className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full bg-gray-100 text-sm font-bold text-gray-600">
          {rank}
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium">{product.name}</p>
          <p className="mt-0.5 text-xs text-gray-500">{product.sku}</p>
        </div>
        <VelocityIndicator trend={product.velocity_trend} velocity={product.velocity} />
      </div>

      <div className="mt-3 flex items-center justify-between border-t pt-3">
        <div>
          <p className="text-xs text-gray-500">Doanh thu</p>
          <p className="text-sm font-semibold">{formatVND(product.revenue)}</p>
        </div>
        <div className="text-right">
          <p className="text-xs text-gray-500">Đã bán</p>
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
  const config = {
    accelerating: {
      icon: "↑",
      color: "text-green-600 bg-green-50",
      testId: "velocity-accelerating",
    },
    decelerating: {
      icon: "↓",
      color: "text-red-600 bg-red-50",
      testId: "velocity-decelerating",
    },
    stable: {
      icon: "→",
      color: "text-gray-600 bg-gray-50",
      testId: "velocity-stable",
    },
  };

  const { icon, color, testId } = config[trend];

  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2 py-1 text-xs font-medium ${color}`}
      data-testid={testId}
    >
      {icon} {velocity.toFixed(1)}/ngày
    </span>
  );
}
