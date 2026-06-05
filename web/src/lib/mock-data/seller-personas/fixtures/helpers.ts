import type { MockOrder, OrderStatus } from "../schemas";

export interface OrderSpec {
  id: string;
  buyerSuffix: string;
  product_title: string;
  quantity: number;
  total_vnd: number;
  status: OrderStatus;
  daysAgo: number;
}

export function buildOrders(shopId: string, specs: OrderSpec[]): MockOrder[] {
  const now = Date.now();

  return specs.map((spec) => ({
    id: spec.id,
    shop_id: shopId,
    buyer_id: `buyer_***${spec.buyerSuffix}`,
    product_title: spec.product_title,
    quantity: spec.quantity,
    total_vnd: spec.total_vnd,
    status: spec.status,
    created_at: new Date(now - spec.daysAgo * 24 * 60 * 60 * 1000).toISOString(),
  }));
}

export function daysAgoIso(daysAgo: number): string {
  return new Date(Date.now() - daysAgo * 24 * 60 * 60 * 1000).toISOString();
}
