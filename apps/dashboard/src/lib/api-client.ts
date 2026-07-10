const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const token =
    typeof window !== "undefined"
      ? localStorage.getItem("access_token")
      : null;

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string>),
  };

  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const shopId =
    typeof window !== "undefined"
      ? localStorage.getItem("active_shop_id")
      : null;

  if (shopId) {
    headers["X-Shop-Id"] = shopId;
  }

  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
  });

  if (!res.ok) {
    const body = await res.text();
    throw new ApiError(res.status, body || res.statusText);
  }

  return res.json();
}

export interface Shop {
  id: string;
  name: string;
  tiktok_shop_id: string;
}

export interface Order {
  id: string;
  order_id: string;
  status: string;
  total_amount: number;
  currency: string;
  created_at: string;
  updated_at: string;
  buyer_name?: string;
  items_count: number;
}

export interface OrdersResponse {
  orders: Order[];
  total: number;
  page: number;
  page_size: number;
}

export interface Product {
  id: string;
  name: string;
  sku: string;
  revenue: number;
  units_sold: number;
  velocity: number;
  velocity_trend: "accelerating" | "decelerating" | "stable";
}

export interface ProductsResponse {
  products: Product[];
  total: number;
}

export interface Creator {
  id: string;
  name: string;
  avatar_url: string | null;
  total_gmv: number;
  commission_paid: number;
  commission_rate: number;
  efficiency_score: number;
  sessions_count: number;
}

export interface CreatorsResponse {
  creators: Creator[];
  total: number;
}

export interface PredictedOutcome {
  gmv_vnd_week: { low: number; high: number };
  conversion_pct: number;
  engagement_index: number;
  risk_factors: string[];
}

export interface RecommendationItem {
  id: string;
  recommendation_type: string;
  message: string;
  cta: string;
  match_score?: number | null;
  confidence?: string | null;
  action_type?: string | null;
  predicted_outcome?: PredictedOutcome | null;
  source?: string | null;
  computed_at?: string | null;
  payload?: Record<string, unknown> | null;
}

export interface RecommendationsResponse {
  items: RecommendationItem[];
}

type RecommendationsApiPayload = {
  success?: boolean;
  data?: RecommendationItem[];
  items?: RecommendationItem[];
};

export const api = {
  shops: {
    list(): Promise<Shop[]> {
      return request("/v1/shops");
    },
    me(): Promise<Shop> {
      return request("/v1/shops/me");
    },
  },

  orders: {
    list(params?: {
      status?: string;
      start_date?: string;
      end_date?: string;
      page?: number;
      page_size?: number;
    }): Promise<OrdersResponse> {
      const searchParams = new URLSearchParams();
      if (params?.status) searchParams.set("status", params.status);
      if (params?.start_date) searchParams.set("start_date", params.start_date);
      if (params?.end_date) searchParams.set("end_date", params.end_date);
      if (params?.page) searchParams.set("page", String(params.page));
      if (params?.page_size)
        searchParams.set("page_size", String(params.page_size));
      const qs = searchParams.toString();
      return request(`/v1/orders${qs ? `?${qs}` : ""}`);
    },
    confirmShipment(orderId: string): Promise<{ success: boolean }> {
      return request(`/v1/orders/${orderId}/ship`, { method: "POST" });
    },
  },

  products: {
    list(): Promise<ProductsResponse> {
      return request("/v1/products");
    },
  },

  creators: {
    list(): Promise<CreatorsResponse> {
      return request("/v1/creators");
    },
  },

  recommendations: {
    async list(): Promise<RecommendationsResponse> {
      const raw = await request<RecommendationsApiPayload>("/v1/recommendations");
      const items = raw.items ?? raw.data ?? [];
      return { items };
    },
  },
};
