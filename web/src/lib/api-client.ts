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

export interface OtpResponse {
  message: string;
}

export interface SessionResponse {
  access_token: string;
  user: { id: string; phone: string };
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

export const api = {
  auth: {
    sendOtp(phone: string): Promise<OtpResponse> {
      return request("/v1/auth/otp/send", {
        method: "POST",
        body: JSON.stringify({ phone }),
      });
    },
    verifyOtp(phone: string, token: string): Promise<SessionResponse> {
      return request("/v1/auth/otp/verify", {
        method: "POST",
        body: JSON.stringify({ phone, token }),
      });
    },
  },

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
};
