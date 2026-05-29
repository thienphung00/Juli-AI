/** Local UI preview without backend (set NEXT_PUBLIC_UI_ONLY=1). */
export const isUiOnly = process.env.NEXT_PUBLIC_UI_ONLY === "1";

export const UI_ONLY_DEMO_USER = {
  id: "00000000-0000-4000-8000-000000000001",
  phone: "+84900000000",
};

export const UI_ONLY_DEMO_TOKEN = "ui-only-demo-token";

export const UI_ONLY_DEMO_SHOP = {
  id: "00000000-0000-4000-8000-000000000002",
  name: "Cửa hàng demo",
  tiktok_shop_id: "demo",
};
