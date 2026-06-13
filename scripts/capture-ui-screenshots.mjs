/**
 * UI screenshot inventory capture for Juli web app.
 * Run: node scripts/capture-ui-screenshots.mjs
 * Requires: dev server at http://localhost:3000 with NEXT_PUBLIC_UI_ONLY=1
 */
import { chromium } from "playwright";
import { mkdir } from "fs/promises";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(__dirname, "..");
const OUT = path.join(ROOT, "screenshots");
const BASE = "http://localhost:3000";

const VIEWPORTS = {
  desktop: { width: 1440, height: 900 },
  tablet: { width: 768, height: 1024 },
  mobile: { width: 390, height: 844 },
};

const AUTH = {
  access_token: "ui-only-demo-token",
  user: JSON.stringify({
    id: "00000000-0000-4000-8000-000000000001",
    phone: "+84900000000",
  }),
  active_shop_id: "00000000-0000-4000-8000-000000000002",
};

const FOLDERS = [
  "dashboard",
  "onboarding",
  "workflows",
  "settings",
  "modals",
  "forms",
  "mobile",
  "tablet",
];

/** @type {{ path: string; screen: string; goal: string; cta: string; notes: string }[]} */
const inventory = [];

async function ensureDirs() {
  for (const folder of FOLDERS) {
    await mkdir(path.join(OUT, folder), { recursive: true });
  }
}

function record(folder, filename, meta) {
  inventory.push({
    path: `${folder}/${filename}`,
    ...meta,
  });
}

async function shot(page, folder, name, viewport, meta) {
  const filename = `${name}-${viewport}.png`;
  const filePath = path.join(OUT, folder, filename);
  await page.screenshot({ path: filePath, fullPage: true });
  record(folder, filename, meta);
  console.log(`  ✓ ${folder}/${filename}`);
}

async function applyStorage(page, entries) {
  await page.goto(BASE, { waitUntil: "domcontentloaded" });
  await page.evaluate((data) => {
    localStorage.clear();
    for (const [k, v] of Object.entries(data)) {
      if (v !== null && v !== undefined) localStorage.setItem(k, v);
    }
  }, entries);
  await page.reload({ waitUntil: "networkidle" });
}

async function setupAuth(page, { mode = "seller", persona = "new" } = {}) {
  await applyStorage(page, {
    access_token: AUTH.access_token,
    user: AUTH.user,
    active_shop_id: AUTH.active_shop_id,
    juli_workspace_mode: mode,
    juli_demo_persona_id: persona,
  });
}

async function setupGuest(page) {
  await applyStorage(page, {
    access_token: null,
    user: null,
    active_shop_id: null,
    juli_workspace_mode: null,
    juli_demo_persona_id: null,
  });
}

async function waitForScreen(page, url, selector, timeout = 15000) {
  await page.goto(url, { waitUntil: "networkidle" });
  await page.waitForSelector(selector, { timeout });
  await page.waitForTimeout(400);
}

async function captureViewports(
  page,
  folder,
  name,
  url,
  meta,
  selector = '[data-testid="seller-home-shell"]',
  viewports = ["desktop", "tablet", "mobile"],
) {
  for (const vp of viewports) {
    await page.setViewportSize(VIEWPORTS[vp]);
    await waitForScreen(page, url, selector);
    await shot(page, folder, `${name}-default`, vp, meta);
  }
}

async function main() {
  await ensureDirs();

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext();
  const page = await context.newPage();

  // ── Onboarding: Login (guest) ──────────────────────────────────────────
  console.log("\n[onboarding] Login");
  await setupGuest(page);

  for (const vp of ["desktop", "tablet", "mobile"]) {
    await page.setViewportSize(VIEWPORTS[vp]);
    await waitForScreen(page, `${BASE}/login`, "#phone");
    await shot(page, "onboarding", "login-phone-empty", vp, {
      screen: "Đăng nhập — Số điện thoại",
      goal: "Xác thực tài khoản người bán",
      cta: "Nhận mã OTP",
      notes: "Bước nhập số điện thoại, chế độ UI-only",
    });
  }

  await page.setViewportSize(VIEWPORTS.desktop);
  await waitForScreen(page, `${BASE}/login`, "#phone");
  await page.fill("#phone", "+84 912 345 678");
  await shot(page, "forms", "login-phone-partial", "desktop", {
    screen: "Đăng nhập — Số đã nhập",
    goal: "Hoàn thành số điện thoại trước khi gửi OTP",
    cta: "Nhận mã OTP",
    notes: "Form điền một phần",
  });

  await page.click('button[type="submit"]');
  await page.waitForTimeout(400);
  await shot(page, "forms", "login-otp-step", "desktop", {
    screen: "Đăng nhập — Nhập OTP",
    goal: "Xác nhận mã OTP",
    cta: "Xác nhận",
    notes: "Bước thứ hai sau gửi OTP",
  });

  // ── Onboarding: Mode select ──────────────────────────────────────────────
  console.log("\n[onboarding] Mode select");
  await applyStorage(page, {
    access_token: AUTH.access_token,
    user: AUTH.user,
    active_shop_id: AUTH.active_shop_id,
    juli_workspace_mode: null,
    juli_demo_persona_id: null,
  });

  for (const vp of ["desktop", "tablet", "mobile"]) {
    await page.setViewportSize(VIEWPORTS[vp]);
    await waitForScreen(page, `${BASE}/mode-select`, 'button[aria-label]');
    await shot(page, "onboarding", "mode-select", vp, {
      screen: "Chọn chế độ workspace",
      goal: "Chọn vai trò Người bán hoặc Affiliate",
      cta: "Chọn Người bán / Affiliate",
      notes: "Gate sau đăng nhập khi chưa có mode",
    });
  }

  // ── Dashboard: Seller personas ─────────────────────────────────────────
  const personas = [
    { id: "new", name: "new-seller", label: "Copilot Người Bán Mới" },
    { id: "leakage", name: "leakage", label: "Phát Hiện Rò Rỉ Doanh Thu" },
    { id: "growth", name: "growth", label: "Copilot Tăng Trưởng" },
  ];

  console.log("\n[dashboard] Seller home personas (read-only, white canvas)");
  for (const persona of personas) {
    await setupAuth(page, { mode: "seller", persona: persona.id });
    await captureViewports(
      page,
      "dashboard",
      `home-${persona.name}`,
      `${BASE}/`,
      {
        screen: `Trang chủ — ${persona.label}`,
        goal: "Xem trạng thái shop, báo cáo hôm nay và sức khỏe cửa hàng (read-only, chart-first)",
        cta: "Gợi ý từ Juli trên metric tile → /decisions?highlight=…",
        notes: `Persona demo: ${persona.id}; ADR-028 white canvas; 3-band layout; no preview/Tiến độ on Home`,
      },
      '[data-testid="home-summary-shell"]',
    );
  }

  console.log("\n[workflows] Decisions tab (Recommended)");
  for (const persona of personas) {
    await setupAuth(page, { mode: "seller", persona: persona.id });
    await captureViewports(
      page,
      "workflows",
      `decisions-recommended-${persona.name}`,
      `${BASE}/decisions`,
      {
        screen: `Quyết định — Đề xuất — ${persona.label}`,
        goal: "Xem danh sách quyết định xếp hạng và phê duyệt",
        cta: "Phê duyệt / Xem trên Trang chủ → (RRAA return)",
        notes: `Persona demo: ${persona.id}; approval gate on Decisions only`,
      },
      '[data-testid="decisions-recommended-shell"]',
    );
  }

  // ── Dashboard: Affiliate out-of-scope ──────────────────────────────────
  console.log("\n[dashboard] Affiliate out-of-scope");
  await setupAuth(page, { mode: "affiliate", persona: "new" });
  await captureViewports(
    page,
    "dashboard",
    "home-affiliate-out-of-scope",
    `${BASE}/`,
    {
      screen: "Trang chủ — Affiliate (ngoài phạm vi MVP)",
      goal: "Thông báo tính năng chưa khả dụng cho Affiliate",
      cta: "Chuyển chế độ workspace (header)",
      notes: "Phase 1: mọi route authenticated hiển thị out-of-scope",
    },
    '[data-testid="affiliate-out-of-scope"]',
    ["desktop", "tablet", "mobile"],
  );

  // ── AI Chat ────────────────────────────────────────────────────────────
  console.log("\n[dashboard] AI Chat");
  await setupAuth(page, { mode: "seller", persona: "new" });
  for (const vp of ["desktop", "tablet", "mobile"]) {
    await page.setViewportSize(VIEWPORTS[vp]);
    await waitForScreen(page, `${BASE}/ai-chat`, '[data-testid="ai-chat-page"] button, [data-testid="ai-chat-page"] textarea');
    await shot(page, "dashboard", "ai-chat-welcome", vp, {
      screen: "Juli AI Chat — Chào mừng",
      goal: "Hỏi đáp với trợ lý AI về cửa hàng",
      cta: "Gợi ý nhanh / Nhập tin nhắn",
      notes: "Tab Juli trong bottom nav",
    });
  }

  await page.setViewportSize(VIEWPORTS.desktop);
  await waitForScreen(page, `${BASE}/ai-chat`, '[data-testid="ai-chat-page"]');
  const prompt = page.locator("button").filter({ hasText: /GMV|đơn hàng|livestream/i }).first();
  if (await prompt.count()) {
    await prompt.click();
    await page.waitForTimeout(1200);
    await shot(page, "dashboard", "ai-chat-conversation", "desktop", {
      screen: "Juli AI Chat — Hội thoại",
      goal: "Nhận phản hồi AI về chủ đề được chọn",
      cta: "Tiếp tục chat",
      notes: "Sau khi chọn gợi ý nhanh",
    });
  }

  // ── Modals & overlays ────────────────────────────────────────────────────
  console.log("\n[modals] Overlays");
  await setupAuth(page, { mode: "seller", persona: "leakage" });
  await page.setViewportSize(VIEWPORTS.desktop);
  await waitForScreen(page, `${BASE}/`, '[data-testid="home-summary-shell"]');

  await page.click('[data-testid="alert-bell-button"]');
  await page.waitForSelector('[data-testid="alert-bell-drawer"]');
  await shot(page, "modals", "alerts-drawer-open", "desktop", {
    screen: "Drawer cảnh báo",
    goal: "Xem cảnh báo workspace",
    cta: "Đóng drawer",
    notes: "Mở từ icon chuông header",
  });
  await page.keyboard.press("Escape");
  await page.waitForTimeout(300);

  const moreMenu = page.locator('[data-testid="task-more-menu"]').first();
  if (await moreMenu.count()) {
    await moreMenu.click();
    await page.waitForTimeout(300);
    await shot(page, "modals", "task-menu-open", "desktop", {
      screen: "Menu tùy chọn nhiệm vụ",
      goal: "Bỏ qua hoặc quản lý nhiệm vụ",
      cta: "Bỏ qua",
      notes: "Dropdown trên TaskCard",
    });
    await page.click('[data-testid="task-dismiss"]');
    await page.waitForSelector('[data-testid="task-dismiss-modal"]');
    await shot(page, "modals", "task-dismiss-modal", "desktop", {
      screen: "Modal bỏ qua nhiệm vụ",
      goal: "Ghi nhận lý do bỏ qua",
      cta: "Xác nhận bỏ qua",
      notes: "Form chọn lý do dismiss",
    });
    await page.click('[data-testid="task-dismiss-cancel"]');
    await page.waitForTimeout(300);
  }

  const evidenceBtn = page.locator('[data-testid="task-view-evidence"]').first();
  if (await evidenceBtn.count()) {
    await evidenceBtn.click();
    await page.waitForTimeout(400);
    await shot(page, "modals", "leakage-evidence-drawer", "desktop", {
      screen: "Drawer bằng chứng rò rỉ",
      goal: "Xem chi tiết bằng chứng bất thường",
      cta: "Đóng",
      notes: "Leakage workflow — masked evidence",
    });
    await page.keyboard.press("Escape");
    await page.waitForTimeout(300);
  }

  const approveBtn = page.locator('[data-testid="task-approve"], [data-testid^="approval-approve-"]').first();
  if (await approveBtn.count()) {
    await approveBtn.click();
    await page.waitForSelector('[data-testid="leakage-workflow"]', { timeout: 8000 });
    await shot(page, "workflows", "leakage-workflow-step1", "desktop", {
      screen: "Workflow rò rỉ — Bước 1",
      goal: "Thực thi hành động khắc phục rò rỉ",
      cta: "Tiếp tục",
      notes: "Modal workflow sau phê duyệt task",
    });

    const nextBtn = page.locator('[data-testid="leakage-next"]');
    if (await nextBtn.count()) {
      await nextBtn.click();
      await page.waitForTimeout(400);
      await shot(page, "workflows", "leakage-workflow-step2", "desktop", {
        screen: "Workflow rò rỉ — Bước 2",
        goal: "Xác nhận chi tiết trước hoàn tất",
        cta: "Tiếp tục / Hoàn tất",
        notes: "Bước chi tiết workflow",
      });
    }
    await page.click('[data-testid="leakage-close"]');
    await page.waitForTimeout(300);
  }

  // ── Workflows: new seller & growth (tablet/mobile copies) ────────────────
  console.log("\n[workflows] Persona panels");
  for (const { id, name, label } of [
    { id: "new", name: "new-seller", label: "Checklist Người Bán Mới" },
    { id: "growth", name: "growth", label: "Copilot Tăng Trưởng" },
  ]) {
    await setupAuth(page, { mode: "seller", persona: id });
    await page.setViewportSize(VIEWPORTS.tablet);
    await waitForScreen(page, `${BASE}/`, '[data-testid="seller-home-shell"]');
    await shot(page, "tablet", `workflow-${name}`, "tablet", {
      screen: `Workflow — ${label}`,
      goal: "Theo dõi tiến độ và nhiệm vụ workflow",
      cta: "Phê duyệt nhiệm vụ",
      notes: `Tablet viewport 768px — persona ${id}`,
    });

    await page.setViewportSize(VIEWPORTS.mobile);
    await waitForScreen(page, `${BASE}/`, '[data-testid="seller-home-shell"]');
    await shot(page, "mobile", `workflow-${name}`, "mobile", {
      screen: `Workflow — ${label}`,
      goal: "Theo dõi tiến độ trên mobile",
      cta: "Phê duyệt nhiệm vụ",
      notes: `Mobile viewport 390px — persona ${id}`,
    });
  }

  // ── New seller listing workflow modal ────────────────────────────────────
  console.log("\n[workflows] Listing workflow");
  await setupAuth(page, { mode: "seller", persona: "new" });
  await page.setViewportSize(VIEWPORTS.desktop);
  await waitForScreen(page, `${BASE}/decisions`, '[data-testid="decisions-recommended-shell"]');
  const listApprove = page.locator('[data-testid^="approval-approve-"]').filter({ hasText: /đăng|listing|sản phẩm|npl/i }).first();
  const anyApprove = page.locator('[data-testid^="approval-approve-"]').first();
  const target = (await listApprove.count()) ? listApprove : anyApprove;
  if (await target.count()) {
    await target.click();
    const listingPanel = page.locator('[data-testid="listing-workflow"], [data-testid="listing-workflow-panel"]');
    await listingPanel.first().waitFor({ timeout: 8000 }).catch(() => {});
    if (await listingPanel.count()) {
      await shot(page, "workflows", "listing-workflow-open", "desktop", {
        screen: "Workflow đăng sản phẩm — Mở",
        goal: "Hoàn thành quy trình đăng listing",
        cta: "Tiếp tục / Hoàn tất",
        notes: "Modal sau phê duyệt task list_products",
      });
      await page.keyboard.press("Escape");
      await page.waitForTimeout(300);
    }
  }

  // ── Nav active states (mobile) ───────────────────────────────────────────
  await setupAuth(page, { mode: "seller", persona: "new" });
  await page.setViewportSize(VIEWPORTS.mobile);
  await waitForScreen(page, `${BASE}/ai-chat`, '[data-testid="ai-chat-page"]');
  await shot(page, "mobile", "nav-ai-chat-active", "mobile", {
    screen: "Bottom nav — Tab Juli active",
    goal: "Chuyển sang chat AI",
    cta: "Juli (tab giữa)",
    notes: "Trạng thái active của bottom navigation",
  });

  await browser.close();

  // Write inventory markdown
  const { writeFile } = await import("fs/promises");
  const lines = ["# Screen Inventory\n"];
  const byFolder = {};
  for (const item of inventory) {
    const folder = item.path.split("/")[0];
  if (!byFolder[folder]) byFolder[folder] = [];
    byFolder[folder].push(item);
  }

  for (const folder of Object.keys(byFolder).sort()) {
    lines.push(`## ${folder.charAt(0).toUpperCase() + folder.slice(1)}\n`);
    for (const item of byFolder[folder]) {
      const file = item.path.split("/")[1];
      lines.push(`* **${file}**`);
      lines.push(`  * Purpose: ${item.screen} — ${item.goal}`);
      lines.push(`  * Primary Action: ${item.cta}`);
      lines.push(`  * Notes: ${item.notes}\n`);
    }
  }

  await writeFile(path.join(OUT, "ui-audit-index.md"), lines.join("\n"));
  console.log(`\n✅ Captured ${inventory.length} screenshots → screenshots/`);
  console.log("   Index: screenshots/ui-audit-index.md");
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
