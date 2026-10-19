#!/usr/bin/env node
/**
 * Blog inline diagrams (D48 additions 7, P39-C). Renders each diagram in
 * DIAGRAMS from HTML with Playwright, in two layouts, and writes under
 * `public/media/`:
 *
 *   blog-fig-<name>-v1-720.avif/.webp, -1440.avif/.webp     (desktop, 720 CSS px wide at 2×)
 *   blog-fig-<name>-m-v1-540.avif/.webp, -1080.avif/.webp   (phones, 360 CSS px wide at 3×)
 *
 * Both layouts are drawn at the size they are shown (the 720 px article column,
 * a 360 px phone column), so the text in the image reads at 13–17 px on both.
 * Colours come from `src/styles/tokens.css`, the face is the self-hosted Be
 * Vietnam Pro (`src/app/fonts/*.woff2`, inlined). Vietnamese text only; every
 * figure that shows a number carries the "Ví dụ giả định" pill (D48 additions 7).
 * No "—" in the text (D46.4).
 *
 * The script prints each layout's CSS height; `src/content/blog/figures.ts`
 * (`diagram(name, height, mobileHeight)`) holds them and `blog.test.tsx` checks
 * them against the files. Files are immutable (cached `immutable`): an existing
 * name is skipped, change a diagram by bumping its `-vN`.
 *
 * Usage (from the repo root; Node 20, Playwright's Chromium installed):
 *
 *   PYTHON=juli/.venv/bin/python node apps/landing/scripts/blog-diagrams.mjs
 *   node apps/landing/scripts/blog-diagrams.mjs --samples <dir>   # PNGs only, nothing in public/
 */

import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { chromium } from "playwright";

const LANDING = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const MEDIA = join(LANDING, "public", "media");
const TOKENS = join(LANDING, "src", "styles", "tokens.css");
const FONTS = join(LANDING, "src", "app", "fonts");
const PYTHON = process.env.PYTHON ?? "python3";

const LAYOUTS = {
  desktop: { width: 720, scale: 2, widths: [720, 1440], suffix: "" },
  mobile: { width: 360, scale: 3, widths: [540, 1080], suffix: "-m" },
};

function readTokens() {
  const css = readFileSync(TOKENS, "utf8");
  const names = [
    "lp-ink", "lp-body", "lp-strong", "lp-muted", "lp-bg", "lp-alt", "lp-hairline", "lp-chrome-dot",
    "lp-pink", "lp-pink-text", "lp-pink-tint", "lp-pink-line", "lp-live-fg", "lp-live-bg",
    "lp-cat-optimize-accent", "lp-backdrop",
  ];
  return Object.fromEntries(
    names.map((name) => {
      const match = new RegExp(`--${name}:\\s*([^;]+);`).exec(css);
      if (!match) throw new Error(`token --${name} not found in ${TOKENS}`);
      return [name.replace(/^lp-/, ""), match[1].trim()];
    }),
  );
}

function fontFaces() {
  const faces = [
    ["regular", 400],
    ["medium", 500],
    ["semibold", 600],
  ];
  return faces
    .map(([file, weight]) => {
      const data = readFileSync(join(FONTS, `be-vietnam-pro-${file}-latin-vi.woff2`)).toString("base64");
      return `@font-face{font-family:"Be Vietnam Pro";font-weight:${weight};src:url(data:font/woff2;base64,${data}) format("woff2")}`;
    })
    .join("\n");
}

/* ————— building blocks ————— */

const PILL = `<span class="pill">Ví dụ giả định</span>`;
const head = (title, example = false) =>
  `<div class="head">${example ? PILL : ""}<p class="title">${title}</p></div>`;
const num = (n, accent = false) => `<span class="num${accent ? " num--accent" : ""}">${n}</span>`;

/* ————— the diagrams ————— */

const DIAGRAMS = [
  {
    name: "gmv-pheu-v1",
    html: () => {
      const rows = [
        ["Lượt hiển thị sản phẩm", "50.000", [100, 100]],
        ["× CTR 3 %"],
        ["Lượt nhấp vào sản phẩm", "1.500", [82, 92]],
        ["× CTOR 4 %"],
        ["Đơn hàng SKU", "60", [64, 84]],
        ["× AOV 180.000 ₫"],
        ["GMV", "10.800.000 ₫", [48, 76], true],
      ];
      return `${head("Một sản phẩm trong 30 ngày", true)}
<div class="funnel">${rows
        .map(([label, value, widths, accent]) =>
          value === undefined
            ? `<div class="op">${label}</div>`
            : `<div class="stage${accent ? " stage--accent" : ""}" style="--w:${widths[0]}%;--wm:${widths[1]}%"><span>${label}</span><strong>${value}</strong></div>`,
        )
        .join("")}</div>
<p class="formula">GMV = Lượt hiển thị sản phẩm × CTR × CTOR × AOV (SKU)</p>`;
    },
  },
  {
    name: "nam-luong-v1",
    html: () => {
      const streams = [
        ["Sản phẩm", "Thẻ sản phẩm", "Tìm kiếm, đề xuất, trang mua sắm", "Hiển thị × CTR × CTOR × AOV", true],
        ["Sản phẩm", "Tab cửa hàng", "Khách chủ động vào trang shop", "Lượt nhấp × CTOR × AOV"],
        ["Nội dung", "Video", "Video do tài khoản shop đăng", "Hiển thị × CTR × CTOR × AOV"],
        ["Nội dung", "LIVE", "Buổi LIVE của shop", "Hiển thị × CTR × CTOR × AOV"],
        ["Liên kết", "Liên kết", "Video và LIVE của nhà sáng tạo", "Hiển thị × CTR × CTOR × AOV"],
      ];
      return `<div class="total"><strong>GMV của shop</strong><span>là tổng của năm luồng truy cập</span></div>
<div class="bracket"></div>
<div class="streams">${streams
        .map(
          ([group, name, from, formula, accent]) =>
            `<div class="box stream${accent ? " box--accent" : ""}"><span class="tag">${group}</span><strong>${name}</strong><span class="from">${from}</span><span class="formula-sm">${formula}</span></div>`,
        )
        .join("")}</div>`;
    },
  },
  {
    name: "buoc-yeu-nhat-v1",
    html: () => {
      const steps = [
        ["Luồng nào thay đổi nhiều nhất?", "So GMV từng luồng giữa hai kỳ dài bằng nhau, theo số tiền chứ không theo phần trăm."],
        ["Hệ số nào trong luồng đó?", "Lượt hiển thị, CTR, CTOR hay AOV: hệ số đổi nhiều nhất là câu chuyện chính."],
        ["So với mốc nào?", "Chính sản phẩm đó ở kỳ trước, và các sản phẩm khác trên cùng luồng."],
        ["Đủ dữ liệu chưa?", "Chưa đủ lượt hiển thị, lượt nhấp, đơn hàng thì ghi “chưa đủ dữ liệu”."],
      ];
      return `${head("Tìm bước yếu nhất trong phễu: bốn câu hỏi theo thứ tự")}
<div class="grid2">${steps
        .map(([q, a], i) => `<div class="box step">${num(i + 1)}<div><strong>${q}</strong><span>${a}</span></div></div>`)
        .join("")}</div>
<div class="result">Kết quả: một điểm nghẽn ở một luồng, một hệ số, trên vài sản phẩm cụ thể</div>`;
    },
  },
  {
    name: "ba-buoc-nghen-v1",
    html: () => {
      const steps = [
        ["Không ai thấy?", "Lượt hiển thị thấp", ["Tiêu đề đúng từ khóa", "Thuộc tính, ngành hàng", "Video, LIVE, nhà sáng tạo"]],
        ["Thấy mà không nhấp?", "CTR thấp", ["Ảnh bìa", "Tiêu đề", "Giá hiển thị"]],
        ["Nhấp mà không mua?", "CTOR thấp", ["Mô tả, bộ ảnh", "Đánh giá, giá", "Phí vận chuyển, voucher"]],
      ];
      return `<div class="chain"><span class="chip">Lượt hiển thị</span><span class="x">×</span><span class="chip">CTR</span><span class="x">×</span><span class="chip">CTOR</span><span class="x">=</span><span class="chip chip--ink">Đơn hàng SKU</span></div>
<div class="grid3">${steps
        .map(
          ([q, metric, fixes], i) =>
            `<div class="box col">${num(i + 1)}<strong>${q}</strong><span class="metric">${metric}</span><span class="label">Sửa ở đâu</span><ul>${fixes.map((f) => `<li>${f}</li>`).join("")}</ul></div>`,
        )
        .join("")}</div>
<p class="note">Một hệ số gần bằng không thì cả tích gần bằng không, dù hai hệ số kia tốt đến đâu.</p>`;
    },
  },
  {
    name: "truoc-gio-sau-gio-v1",
    html: () => `${head("Tách CTOR làm hai nửa")}
<div class="flow">
  <div class="box node">Lượt nhấp vào sản phẩm</div>
  <div class="arrow"><span>Tỷ lệ thêm vào giỏ hàng</span></div>
  <div class="box node">Thêm vào giỏ hàng</div>
  <div class="arrow"><span>Thanh toán</span></div>
  <div class="box node node--ink">Đơn hàng SKU</div>
</div>
<div class="grid2 halves">
  <div class="box half"><strong>Trước giỏ: chưa bị thuyết phục</strong><span class="label">Xem lại</span><ul><li>Bộ ảnh chi tiết</li><li>Mô tả sản phẩm</li><li>Đánh giá</li><li>Giá so với sản phẩm tương tự</li></ul></div>
  <div class="box half"><strong>Sau giỏ: bỏ ở bước thanh toán</strong><span class="label">Xem lại</span><ul><li>Phí vận chuyển</li><li>Voucher đã hết hạn</li><li>Khách chờ đợt ưu đãi tiếp theo</li></ul></div>
</div>
<p class="note">Người xem video hay LIVE có thể mua ngay mà không qua giỏ, nên cách tách này chính xác nhất ở luồng Thẻ sản phẩm và Tab cửa hàng.</p>`,
  },
  {
    name: "quang-cao-ab-v1",
    html: () => `${head("Một sản phẩm, mỗi tuần", true)}
<div class="box now"><span class="label">Hiện tại</span><span class="eq">10.000 lượt hiển thị × CTR 1 % × CTOR 1 %</span><strong class="res">1 đơn</strong></div>
<div class="grid2">
  <div class="box option"><span class="label">Phương án A</span><strong>Gấp đôi traffic</strong><span class="eq">20.000 × CTR 1 % × CTOR 1 %</span><strong class="res">2 đơn</strong><span class="small">Thường ít hơn: traffic mua thêm hay có CTR thấp hơn.</span></div>
  <div class="box option box--accent"><span class="label">Phương án B</span><strong>Sửa trang sản phẩm</strong><span class="eq">10.000 × CTR 1 % × CTOR 3 %</span><strong class="res">3 đơn</strong><span class="small">Mô tả đầy đủ, ảnh kích thước, trả lời câu hỏi hay gặp.</span></div>
</div>
<div class="result">Sửa phễu trước, rồi mới mua thêm traffic</div>`,
  },
  {
    name: "so-sanh-hai-ky-v1",
    html: () => {
      const days = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"];
      const week = (sale) =>
        days.map((d, i) => `<span class="day${sale === i ? " day--sale" : ""}">${d}</span>`).join("");
      const rules = [
        "Hai kỳ dài bằng nhau",
        "Bắt đầu cùng một thứ trong tuần",
        "Đánh dấu ngày sale lớn",
        "Không tính ngày hôm nay",
        "Cùng một loại GMV",
      ];
      return `${head("So sánh hai kỳ cho công bằng")}
<div class="periods">
  <div class="period"><span class="label">Kỳ trước</span><div class="days">${week(4)}</div></div>
  <div class="period"><span class="label">Kỳ này</span><div class="days">${week(-1)}<span class="day day--today">Hôm nay</span></div></div>
</div>
<div class="legend"><span><i class="sw sw--sale"></i>Ngày sale: ghi chú riêng khi so</span><span><i class="sw sw--today"></i>Chưa hết ngày: không tính</span></div>
<ul class="rules">${rules.map((r) => `<li><span class="check">✓</span>${r}</li>`).join("")}</ul>`;
    },
  },
  {
    name: "giam-theo-luong-v1",
    html: () => {
      const rows = [
        ["Thẻ sản phẩm", -2.7, "−2.700.000 ₫", "90 % mức giảm"],
        ["Tab cửa hàng", -0.2, "−200.000 ₫"],
        ["Video", 0.2, "+200.000 ₫"],
        ["LIVE", 0.4, "+400.000 ₫"],
        ["Liên kết", -0.7, "−700.000 ₫"],
      ];
      const max = 3;
      const bar = (v) => {
        const w = (Math.abs(v) / max) * 50;
        const side = v < 0 ? `right:50%` : `left:50%`;
        return `<span class="bar ${v < 0 ? "bar--neg" : "bar--pos"}" style="${side};width:${w}%"></span>`;
      };
      return `${head("Thay đổi GMV theo luồng, 30 ngày so với 30 ngày trước", true)}
<div class="legend"><span><i class="sw sw--neg"></i>Giảm</span><span><i class="sw sw--pos"></i>Tăng</span></div>
<div class="bars">${rows
        .map(
          ([label, v, text, note]) =>
            `<div class="brow"><span class="blabel">${label}</span><span class="track"><i class="zero"></i>${bar(v)}</span><span class="bval">${text}${note ? `<em>${note}</em>` : ""}</span></div>`,
        )
        .join("")}
<div class="brow brow--total"><span class="blabel">Toàn shop</span><span class="track"><i class="zero"></i><span class="bar bar--ink" style="right:50%;width:50%"></span></span><span class="bval">−3.000.000 ₫</span></div>
</div>
<p class="note">Đọc theo số tiền trước, phần trăm sau: gần như toàn bộ mức giảm nằm ở một luồng.</p>`;
    },
  },
  {
    name: "quy-trinh-30-phut-v1",
    html: () => {
      const steps = [
        ["Kiểm tra cách so sánh", "Hai kỳ bằng nhau, cùng loại GMV, đánh dấu ngày sale."],
        ["Tách GMV theo năm luồng", "Tìm luồng giảm nhiều nhất theo số tiền."],
        ["Tách luồng đó thành bốn chỉ số", "Lượt hiển thị, CTR, CTOR, AOV."],
        ["Đi qua danh sách kiểm tra", "Của đúng luồng và đúng chỉ số."],
        ["Tìm năm sản phẩm", "Giải thích nhiều nhất mức giảm."],
        ["Kiểm tra ngoài phễu", "Mùa vụ, hủy, hoàn, sản phẩm ngừng bán."],
        ["Ghi một kết luận, một hành động", "Kèm ngày bắt đầu, để kỳ sau đo lại.", true],
      ];
      return `${head("Quy trình 30 phút khi doanh thu giảm")}
<div class="grid2 process">${steps
        .map(
          ([t, d, accent], i) =>
            `<div class="box step${accent ? " box--accent step--wide" : ""}">${num(i + 1, accent)}<div><strong>${t}</strong><span>${d}</span></div></div>`,
        )
        .join("")}</div>`;
    },
  },
  /* ————— P39-D (D48 additions 8) ————— */
  {
    name: "truoc-khi-doc-pheu-v1",
    html: () => {
      const statuses = [
        ["Trực tuyến", "Khách mua được", true],
        ["Đã vô hiệu hóa", "Người bán cho ngừng hiển thị"],
        ["Đã tạm ngưng", "Ví dụ bị từ chối khi duyệt"],
        ["Bản nháp", "Chưa gửi đi"],
      ];
      return `${head("Ba kiểm tra trước khi đọc phễu")}
<div class="box sect"><div class="sect-head">${num(1)}<strong>Trạng thái sản phẩm</strong></div>
<div class="statuses">${statuses
        .map(
          ([name, what, ok]) =>
            `<div class="status${ok ? " status--ok" : ""}"><span class="verdict">${ok ? "Bán được" : "Không bán được"}</span><strong>${name}</strong><span class="small">${what}</span></div>`,
        )
        .join("")}</div></div>
<div class="grid2">
  <div class="box step">${num(2)}<div><strong>Tồn kho từng biến thể</strong><span>Biến thể khách chọn nhiều nhất còn hàng, không chỉ tổng tồn kho của sản phẩm.</span></div></div>
  <div class="box step">${num(3)}<div><strong>Vận hành shop</strong><span>Giao đúng hạn, xử lý nhanh đơn mới, để thẻ sản phẩm giữ vị trí trong nhóm đề xuất.</span></div></div>
</div>
<div class="result">Cả ba đều ổn mới bắt đầu đọc phễu</div>`;
    },
  },
  {
    name: "doc-pheu-o-dau-v3",
    html: () => {
      const path = ["Trung tâm nhà bán hàng", "La bàn dữ liệu", "Số liệu phân tích sản phẩm", "Lưu lượng truy cập sản phẩm"];
      const rules = [
        ["Chọn luồng", "Đọc Thẻ sản phẩm trước: không có người dẫn LIVE hay nhà sáng tạo bán hộ."],
        ["Chọn khoảng thời gian", "Ít nhất 14 ngày, tốt hơn 28 hoặc 30 ngày. Cộng tổng cả kỳ rồi mới chia ra tỷ lệ."],
        ["Đủ dữ liệu chưa", "Chỉ đọc tỷ lệ khi số liệu đủ nhiều để không bị nhiễu, và giữ cùng một cách đọc cho mọi lần so sánh."],
      ];
      return `${head("Phễu của từng sản phẩm nằm ở đâu", true)}
<div class="path">${path
        .map((p, i) => `<span class="crumb${i === path.length - 1 ? " crumb--ink" : ""}">${p}</span>`)
        .join(`<span class="sep">›</span>`)}</div>
<p class="label">Rồi đọc theo ba quy tắc</p>
<div class="grid3">${rules
        .map(([t, d], i) => `<div class="box col">${num(i + 1)}<strong>${t}</strong><span class="desc">${d}</span></div>`)
        .join("")}</div>
<p class="note">TikTok không đưa ra ngưỡng chính thức cho mục 3. Khi số liệu còn quá ít, ghi “chưa đủ dữ liệu”: vấn đề thường nằm ở Lượt hiển thị.</p>`;
    },
  },
  {
    name: "luong-noi-dung-v1",
    html: () => {
      const cards = [
        ["Video", "Có lượt xem, ít lượt nhấp vào sản phẩm", ["Video cho thấy rõ sản phẩm, công dụng, giá", "Sản phẩm được gắn đúng"]],
        ["LIVE", "Có người xem, không ra đơn", ["Thời điểm giới thiệu sản phẩm", "Ưu đãi trong phiên", "Sản phẩm được ghim còn hàng"]],
        ["Liên kết", "Có lượt hiển thị, ít đơn", ["Khán giả của nhà sáng tạo có khớp với sản phẩm"]],
      ];
      return `${head("Luồng nội dung không ra đơn: xem gì trước")}
<div class="grid3 cards">${cards
        .map(
          ([name, sign, checks]) =>
            `<div class="box col"><span class="tag">${name}</span><strong>${sign}</strong><span class="label">Kiểm tra</span><ul class="hang">${checks.map((c) => `<li>${c}</li>`).join("")}</ul></div>`,
        )
        .join("")}</div>
<p class="note">Ở ba luồng này, chỉ số chính là Lượt hiển thị sản phẩm và GMV; CTOR chỉ để tham khảo.</p>
<div class="result">Mọi lượt nhấp đều về trang sản phẩm: nếu CTOR ở Thẻ sản phẩm cũng thấp, sửa trang trước</div>`;
    },
  },
  {
    name: "kiem-tra-theo-chi-so-v1",
    html: () => {
      const metrics = [
        ["Lượt hiển thị sản phẩm giảm", ["Trạng thái, hết hàng, tiêu đề mất từ khóa", "Ít video, buổi LIVE, nhà sáng tạo hơn", "Kỳ trước có ngày sale, kỳ này không", "Vận hành xấu đi, tụt khỏi nhóm đề xuất"]],
        ["CTR giảm", ["Traffic loãng: kiểm tra đầu tiên", "Ảnh bìa, tiêu đề, giá hiển thị vừa đổi", "Chiết khấu hay nhãn khuyến mãi vừa hết", "Sản phẩm cạnh tranh mới, giá thấp hơn"]],
        ["CTOR giảm", ["Tỷ lệ thêm vào giỏ hàng giảm: giá, bộ ảnh, mô tả, đánh giá mới", "Thêm vào giỏ vẫn vậy mà ít đơn: phí vận chuyển, voucher, khách chờ ưu đãi"]],
        ["AOV giảm", ["Mua Sỉ Giá Hời vừa kết thúc", "Khách chuyển sang biến thể rẻ hơn", "Vừa giảm giá sâu hơn", "Ưu đãi theo gói, quà tặng kèm vừa tắt"]],
      ];
      return `<div class="chain"><span class="chip">Lượt hiển thị</span><span class="x">×</span><span class="chip">CTR</span><span class="x">×</span><span class="chip">CTOR</span><span class="x">×</span><span class="chip">AOV</span><span class="x">=</span><span class="chip chip--ink">GMV</span></div>
<p class="title center">Chỉ số nào giảm nhiều nhất, tìm nguyên nhân ở đó</p>
<div class="grid2">${metrics
        .map(
          ([metric, items]) =>
            `<div class="box half"><strong class="metric">${metric}</strong><span class="label">Xem lại</span><ul class="hang">${items.map((i) => `<li>${i}</li>`).join("")}</ul></div>`,
        )
        .join("")}</div>`;
    },
  },
  {
    name: "ngoai-pheu-v1",
    html: () => {
      const causes = [
        ["Mùa vụ", "Ngành hàng có tháng cao điểm và tháng thấp điểm.", "So với cùng kỳ năm trước, nếu shop đủ lâu."],
        ["Đơn hủy, hoàn tiền tăng", "Tiền về giảm mạnh hơn GMV.", "Lý do hủy và lý do hoàn."],
        ["Hoàn tiền đến muộn", "Ghi vào ngày yêu cầu được xử lý, không phải ngày mua.", "Tỷ lệ hoàn của tuần gần nhất, thường trông thấp hơn thực tế."],
        ["Sản phẩm chủ lực ngừng bán", "Hết hàng dài ngày, ngừng nhập, bị tạm ngưng.", "Trạng thái và tồn kho của sản phẩm đó."],
      ];
      return `${head("Nguyên nhân nằm ngoài phễu")}
<div class="grid2 vs">
  <div class="box"><strong>GMV</strong><span class="small">Tính cả đơn đã hủy và hoàn tiền</span></div>
  <div class="box"><strong>Tiền về</strong><span class="small">Sau hủy, hoàn và các khoản phí</span></div>
</div>
<div class="grid2">${causes
        .map(
          ([t, sign, check], i) =>
            `<div class="box step">${num(i + 1)}<div><strong>${t}</strong><span>${sign}</span><span class="look"><b>Xem:</b> ${check}</span></div></div>`,
        )
        .join("")}</div>
<p class="note">Bốn nguyên nhân này không nằm ở trang sản phẩm: kiểm tra trước khi sửa phễu.</p>`;
    },
  },
  /* ————— P46-B2 (D56): san-pham-tiktok-shop-khong-co-luot-hien-thi ————— */
  {
    name: "an-hay-it-thay-v1",
    html: () => `${head("Sản phẩm bị ẩn, hay chỉ ít người thấy?")}
<div class="grid2">
  <div class="box half"><strong>Không hiện với người mua</strong><span class="label">Dấu hiệu</span><ul><li>Trạng thái không phải Trực tuyến</li><li>Không có Lượt hiển thị ở luồng nào</li></ul><span class="label">Xem ở đâu</span><ul><li>Trạng thái và lý do trong Quản lý sản phẩm</li><li>Sửa theo chính sách rồi gửi lại</li></ul></div>
  <div class="box half box--accent"><strong>Đang hiện, nhưng ít người thấy</strong><span class="label">Dấu hiệu</span><ul><li>Trực tuyến, còn hàng ở biến thể chính</li><li>Có Lượt hiển thị, nhưng thấp so với chính shop</li></ul><span class="label">Xem ở đâu</span><ul><li>Lượt hiển thị theo năm luồng</li><li>Luồng nào thiếu, luồng nào có mà ít nhấp</li></ul></div>
</div>
<div class="result">Sửa lỗi hiển thị trước, rồi mới đọc Lượt hiển thị</div>`,
  },
  {
    name: "hien-thi-theo-luong-v1",
    html: () => {
      const rows = [
        ["Thẻ sản phẩm", "Tìm kiếm, đề xuất, trang mua sắm. Tiêu đề có từ khóa người mua tìm, thuộc tính và ngành hàng đã đúng chưa?"],
        ["Tab cửa hàng", "Khách tự vào trang shop. TikTok không chia Lượt hiển thị cho luồng này: đọc Lượt nhấp."],
        ["Video", "Video của shop có gắn sản phẩm này không, có đăng đều không?"],
        ["LIVE", "Sản phẩm có được giới thiệu và ghim trong buổi LIVE không?"],
        ["Liên kết", "Có nhà sáng tạo nào đang gắn sản phẩm này trong video hay LIVE của họ không?", true],
      ];
      return `${head("Lượt hiển thị đến từ đâu: năm luồng, năm câu hỏi")}
<div class="grid2 process">${rows
        .map(
          ([t, d, wide], i) =>
            `<div class="box step${wide ? " step--wide" : ""}">${num(i + 1)}<div><strong>${t}</strong><span>${d}</span></div></div>`,
        )
        .join("")}</div>
<div class="result">Luồng không có lượt hiển thị là chỗ thiếu; luồng có mà ít nhấp là chuyện của CTR</div>`;
    },
  },
  {
    name: "hien-thi-ctr-v1",
    html: () => {
      const cells = [
        ["Ít hiển thị, CTR cao", "Người thấy thì nhấp: sản phẩm thiếu chỗ xuất hiện.", ["Từ khóa trong tiêu đề", "Video, LIVE, nhà sáng tạo"], true],
        ["Ít hiển thị, CTR thấp", "Kéo thêm người xem lúc này dễ phí.", ["Ảnh bìa và tiêu đề trước", "Rồi mới thêm chỗ xuất hiện"]],
        ["Hiển thị ổn, CTR thấp", "Lượt hiển thị không phải điểm nghẽn.", ["Ảnh bìa, tiêu đề", "Giá hiển thị"]],
        ["Hiển thị ổn, CTR ổn", "Bước sau mới là chỗ cần xem.", ["CTOR: trang sản phẩm có thuyết phục người đã nhấp"]],
      ];
      return `${head("Đọc Lượt hiển thị cùng CTR")}
<div class="grid2">${cells
        .map(
          ([t, d, items, accent]) =>
            `<div class="box half${accent ? " box--accent" : ""}"><strong class="metric">${t}</strong><span class="desc">${d}</span><span class="label">Xem lại</span><ul class="hang">${items.map((i) => `<li>${i}</li>`).join("")}</ul></div>`,
        )
        .join("")}</div>
<p class="note">“Ít” và “ổn” là so với chính sản phẩm đó ở kỳ trước và với sản phẩm khác trên cùng luồng: TikTok không công bố một mức chuẩn chung.</p>`;
    },
  },
  {
    name: "theo-doi-7-14-v1",
    html: () => {
      const path = ["14 ngày trước: mốc so sánh", "Ngày duyệt: thay đổi lên shop", "Ngày 7: đọc sơ bộ", "Ngày 14: chốt kết quả"];
      const rules = [
        ["Một thay đổi một lúc", "Trên một sản phẩm, để biết kết quả là của thay đổi nào."],
        ["Đúng chỉ số được nhắm", "Sửa tiêu đề để thêm từ khóa thì đọc Lượt hiển thị ở Thẻ sản phẩm trước."],
        ["So với sản phẩm không đổi", "Cả shop cùng tăng thì chưa chắc là nhờ thay đổi."],
      ];
      return `${head("Sau khi sửa: một thay đổi, một mốc thời gian")}
<div class="path">${path
        .map((p, i) => `<span class="crumb${i === path.length - 1 ? " crumb--ink" : ""}">${p}</span>`)
        .join(`<span class="sep">›</span>`)}</div>
<div class="grid3">${rules
        .map(([t, d], i) => `<div class="box col">${num(i + 1)}<strong>${t}</strong><span class="desc">${d}</span></div>`)
        .join("")}</div>
<div class="result">Không sửa tiếp sản phẩm đó cho đến ngày 14</div>`;
    },
  },
  /* ————— P46-B2 (D56): thue-ban-hang-tiktok-shop ————— */
  {
    name: "khau-tru-san-v1",
    html: () => {
      const path = ["Khách đặt hàng và thanh toán", "Giao dịch thành công, sàn chấp nhận thanh toán", "Sàn khấu trừ thuế GTGT và TNCN", "Người bán nhận phần còn lại"];
      return `${head("Sàn khấu trừ thuế trên từng giao dịch")}
<div class="path">${path
        .map((p, i) => `<span class="crumb${i === path.length - 1 ? " crumb--ink" : ""}">${p}</span>`)
        .join(`<span class="sep">›</span>`)}</div>
<div class="grid2">
  <div class="box half"><strong>Sàn làm</strong><ul><li>Khai và nộp thay số thuế đã khấu trừ, theo tháng</li><li>Bù trừ thuế của đơn bị hủy hoặc trả hàng</li><li>Trả lại cho người bán số thuế đã trừ của các đơn đó</li></ul></div>
  <div class="box half"><strong>Người bán làm</strong><ul><li>Cung cấp cho sàn mã số thuế hoặc số định danh cá nhân</li><li>Báo cơ quan thuế các tài khoản thanh toán dùng để kinh doanh</li><li>Giữ sổ kế toán, dùng hóa đơn theo quy định</li></ul></div>
</div>
<p class="note">Tỷ lệ khấu trừ do luật thuế quy định, không do sàn tự đặt.</p>`;
    },
  },
  {
    name: "nguong-1-ty-v1",
    html: () => {
      const cols = [
        ["Từ 1 tỷ đồng trở xuống", "Không chịu thuế GTGT, không nộp thuế TNCN. Đã bị sàn khấu trừ thì làm thủ tục bù trừ hoặc hoàn số nộp thừa.", true],
        ["Trên 1 tỷ đến 3 tỷ đồng", "Tính thuế trên doanh thu, hoặc chọn tính TNCN theo thu nhập. Chọn theo thu nhập thì tổng hợp doanh thu, quyết toán TNCN theo năm."],
        ["Trên 3 tỷ đồng", "Tính TNCN theo thu nhập (doanh thu trừ chi phí); tổng hợp doanh thu, quyết toán TNCN theo năm."],
      ];
      return `${head("Doanh thu cả năm của hộ, cá nhân kinh doanh")}
<div class="grid3">${cols
        .map(
          ([t, d, accent], i) =>
            `<div class="box col${accent ? " box--accent" : ""}">${num(i + 1, accent)}<strong>${t}</strong><span class="desc">${d}</span></div>`,
        )
        .join("")}</div>
<p class="note">Khi quyết toán, doanh thu trên sàn được tổng hợp cùng doanh thu bán ngoài sàn; số TNCN sàn đã trừ được trừ vào số phải nộp. Trên 1 tỷ đồng phải dùng hóa đơn điện tử.</p>`;
    },
  },
  /* ————— P46-B1 (D56): video-tiktok-nhieu-view-khong-ra-don ————— */
  {
    name: "video-view-den-don-v1",
    html: () => {
      const rows = [
        ["Lượt hiển thị sản phẩm", "20.000", [100, 100]],
        ["× CTR 1 %", true],
        ["Lượt nhấp vào sản phẩm", "200", [80, 90], true],
        ["× CTOR 4 %"],
        ["Đơn hàng SKU", "8", [62, 80]],
        ["× AOV 150.000 ₫"],
        ["GMV", "1.200.000 ₫", [48, 72]],
      ];
      return `${head("Một video trong 28 ngày", true)}
<div class="box vv"><div><span class="label">Lượt xem video</span><strong class="vv-num">100.000</strong></div><span class="small">Chỉ số của video. Không có trong công thức GMV.</span></div>
<div class="funnel">${rows
        .map(([label, value, widths, accent]) =>
          typeof value !== "string"
            ? `<div class="op${value ? " op--accent" : ""}">${label}</div>`
            : `<div class="stage${accent ? " stage--accent" : ""}" style="--w:${widths[0]}%;--wm:${widths[1]}%"><span>${label}</span><strong>${value}</strong></div>`,
        )
        .join("")}</div>
<p class="note">Chỗ gãy trong ví dụ là CTR: cứ 100 lần sản phẩm hiện ra thì 99 lần không ai bấm vào.</p>`;
    },
  },
  {
    name: "video-trieu-chung-v1",
    html: () => {
      const rows = [
        ["Nhiều lượt xem, ít Lượt hiển thị sản phẩm", "Sản phẩm ít được nhìn thấy", ["Sản phẩm có được gắn đúng vào video", "Video có nói về sản phẩm hay chỉ giải trí"]],
        ["Lượt hiển thị sản phẩm ổn, CTR thấp", "Thấy mà không bấm", ["Video cho thấy rõ sản phẩm, công dụng, giá", "Người xem có phải người cần sản phẩm này"]],
        ["CTR ổn, CTOR thấp", "Bấm vào mà không mua", ["Ảnh, mô tả, đánh giá trên trang sản phẩm", "Giá và ưu đãi có khớp điều video nói"]],
        ["Có đơn, GMV vẫn thấp", "AOV thấp", ["Khách chọn biến thể rẻ nhất", "Có ưu đãi mua nhiều hay mua theo gói"]],
      ];
      return `${head("Triệu chứng, bước nghi ngờ và việc cần xem")}
<div class="grid2">${rows
        .map(
          ([sign, step, checks], i) =>
            `<div class="box half"><div class="sect-head">${num(i + 1)}<strong>${sign}</strong></div><span class="metric">${step}</span><span class="label">Xem lại</span><ul class="hang">${checks.map((c) => `<li>${c}</li>`).join("")}</ul></div>`,
        )
        .join("")}</div>
<p class="note">So với chính video đó ở kỳ trước và với các video khác của shop, trên cùng luồng Video.</p>`;
    },
  },
  {
    name: "video-truc-tiep-gian-tiep-v1",
    html: () => {
      const paths = [
        ["Xem video, bấm vào sản phẩm, mua ngay", "GMV video trực tiếp", true],
        ["Xem video, bấm vào sản phẩm, vài ngày sau tự tìm lại và mua", "GMV video gián tiếp, nếu mua trong 7 ngày"],
        ["Chỉ xem video, không bấm vào sản phẩm", "Không ghi nhận cho video"],
      ];
      return `${head("Đơn nào được tính cho video")}
<div class="grid3 cards paths">${paths
        .map(
          ([what, result, accent], i) =>
            `<div class="box col${accent ? " box--accent" : ""}">${num(i + 1, accent)}<strong>${what}</strong><span class="label">Ghi nhận</span><span class="metric">${result}</span></div>`,
        )
        .join("")}</div>
<p class="note">Theo Học viện TikTok Shop (bài Tinh chỉnh GMV): người mua phải xem và bấm vào link sản phẩm thì video mới được tính; nếu xem nhiều nội dung, đơn được ghi nhận cho nội dung cuối cùng.</p>`;
    },
  },
  {
    name: "video-sua-va-do-v1",
    html: () => {
      const steps = [
        ["Đọc luồng Video 28 ngày", "Cộng tổng cả kỳ rồi mới chia ra tỷ lệ."],
        ["Tìm bước gãy", "Lượt hiển thị sản phẩm, CTR, CTOR hay AOV."],
        ["Chọn một thay đổi", "Video mới do bạn quay, hoặc trang sản phẩm, không làm cả hai cùng lúc."],
        ["Ghi ngày bắt đầu", "Để biết số liệu nào là trước, số liệu nào là sau."],
        ["Ngày 7: đọc sơ bộ", "Chỉ số mục tiêu đang lên, đi ngang hay giảm."],
        ["Ngày 14: chốt", "Giữ thay đổi, sửa tiếp hoặc quay lại bản cũ.", true],
      ];
      return `${head("Sửa một chỗ, đo lại sau 7 và 14 ngày")}
<div class="grid2 process">${steps
        .map(
          ([t, d, accent], i) =>
            `<div class="box step${accent ? " box--accent" : ""}">${num(i + 1, accent)}<div><strong>${t}</strong><span>${d}</span></div></div>`,
        )
        .join("")}</div>`;
    },
  },
  /* ————— P46-B1 (D56): live-tiktok-shop-khong-ra-don ————— */
  {
    name: "live-pheu-v1",
    html: () => {
      const rows = [
        ["Lượt hiển thị LIVE", "60.000", [100, 100]],
        ["Tỷ lệ vào phòng (ERR) 8 %"],
        ["Lượt xem LIVE", "4.800", [86, 92]],
        ["Sản phẩm được ghim, giỏ hàng"],
        ["Lượt hiển thị sản phẩm", "3.600", [74, 86]],
        ["Còn 2,5 %", true],
        ["Lượt nhấp vào sản phẩm", "90", [60, 78], true],
        ["Còn 6,7 %"],
        ["Đơn hàng đã thanh toán", "6", [48, 70]],
      ];
      return `${head("Một buổi LIVE, năm bước của TikTok", true)}
<div class="funnel">${rows
        .map(([label, value, widths, accent]) =>
          typeof value !== "string"
            ? `<div class="op${value ? " op--accent" : ""}">${label}</div>`
            : `<div class="stage${accent ? " stage--accent" : ""}" style="--w:${widths[0]}%;--wm:${widths[1]}%"><span>${label}</span><strong>${value}</strong></div>`,
        )
        .join("")}</div>
<p class="note">4.800 lượt xem nhưng chỉ 90 lượt nhấp: trong ví dụ, chỗ tụt mạnh nhất là từ thấy sản phẩm đến bấm vào sản phẩm.</p>`;
    },
  },
  {
    name: "live-ba-goc-do-v1",
    html: () => {
      const groups = [
        ["Phạm vi tiếp cận", ["Lượt hiển thị", "Lượt xem", "Tỷ lệ vào phòng (ERR)", "Thời lượng xem trung bình"]],
        ["Tương tác", ["Tỷ lệ bình luận", "Tỷ lệ theo dõi", "Tỷ lệ chia sẻ", "Tỷ lệ thích"]],
        ["Chuyển đổi", ["CTR", "CTOR", "GPM hiển thị", "GPM lượt xem"], true],
      ];
      return `${head("Ba góc độ của chỉ số LIVE")}
<div class="grid3 cards paths">${groups
        .map(
          ([name, items, accent]) =>
            `<div class="box col${accent ? " box--accent" : ""}"><strong>${name}</strong><ul class="hang">${items.map((m) => `<li>${m}</li>`).join("")}</ul></div>`,
        )
        .join("")}</div>
<p class="note">Đông người xem chỉ nói về góc độ đầu tiên. Đơn hàng nằm ở góc độ thứ ba.</p>
<p class="small">Trong Cẩm nang lưu lượng LIVE, CTR của LIVE là lượt bấm vào sản phẩm chia cho lượt xem LIVE, khác cách tính CTR của thẻ sản phẩm.</p>`;
    },
  },
  {
    name: "live-gpm-v1",
    html: () => `${head("Hai buổi LIVE của cùng một shop", true)}
<div class="grid2">
  <div class="box option"><span class="label">Buổi A</span><strong>Đông người xem</strong><span class="eq">50.000 lượt hiển thị · 3.000 lượt xem</span><span class="eq">GMV 4.000.000 ₫</span><strong class="res">GPM hiển thị 80.000 ₫</strong></div>
  <div class="box option box--accent"><span class="label">Buổi B</span><strong>Ít người xem hơn</strong><span class="eq">20.000 lượt hiển thị · 1.200 lượt xem</span><span class="eq">GMV 3.000.000 ₫</span><strong class="res">GPM hiển thị 150.000 ₫</strong></div>
</div>
<p class="formula">GPM hiển thị = GMV phòng LIVE ÷ Lượt hiển thị × 1.000</p>
<div class="result">Buổi B ít người hơn nhưng mỗi 1.000 lượt hiển thị bán được gần gấp đôi</div>`,
  },
  {
    name: "live-trong-sau-v1",
    html: () => `${head("Đọc số liệu LIVE: trong buổi và sau buổi")}
<div class="grid2">
  <div class="box half"><strong>Trong khi LIVE</strong><span class="label">Theo dõi</span><ul class="hang"><li>Xu hướng Lượt hiển thị và ERR</li><li>Chỉ số đổi ra sao khi đổi sản phẩm ghim, flash sale, tặng phẩm</li><li>ERR cần khoảng 15 đến 30 phút đầu để ổn định</li></ul></div>
  <div class="box half"><strong>Sau khi LIVE</strong><span class="label">Xem lại</span><ul class="hang"><li>3 chỉ số kém nhất, so với các buổi gần đây</li><li>Lúc chỉ số giảm: sản phẩm nào đang ghim, ưu đãi nào đang chạy, có vi phạm không</li><li>Dữ liệu cấp tài khoản ít nhất 7 ngày một lần</li></ul></div>
</div>
<div class="result">Chọn một thay đổi cho buổi sau, rồi so lại trên cùng các chỉ số</div>`,
  },
  /* ————— P46-C2 (D56): ty-le-hoan-hang-tiktok-shop ————— */
  {
    name: "ba-loai-hoan-hang-v1",
    html: () => {
      const cols = [
        ["Hủy đơn", "Trước khi đơn ở trạng thái đang vận chuyển", "SFCR, nếu do lỗi người bán: hết hàng, sai giá, không bàn giao kịp", "Hàng chưa rời shop"],
        ["Giao không thành công", "Đơn hủy khi đang vận chuyển, hoặc khách COD từ chối nhận", "Không có chỉ số riêng", "Hàng quay về shop, người bán chịu phí chuyển hoàn"],
        ["Trả hàng, hoàn tiền", "Sau khi đơn đã giao, khách gửi yêu cầu", "SFRR, nếu lý do liên quan người bán: không đúng mô tả, gửi sai, lỗi, thiếu", "Trả hàng về shop, hoặc chỉ hoàn tiền"],
      ];
      return `${head("“Hoàn hàng” là ba loại đơn khác nhau")}
<div class="grid3">${cols
        .map(
          ([t, when, metric, goods], i) =>
            `<div class="box col">${num(i + 1)}<strong>${t}</strong><span class="label">Khi nào</span><span class="desc">${when}</span><span class="label">Chỉ số</span><span class="desc">${metric}</span><span class="label">Hàng hóa</span><span class="desc">${goods}</span></div>`,
        )
        .join("")}</div>
<div class="result">Tách ba loại trước, rồi mới xem loại nào đang tăng</div>`;
    },
  },
  {
    name: "dong-thoi-gian-tra-hang-v1",
    html: () => {
      const path = [
        "Khách gửi yêu cầu: trong 15 ngày theo lịch sau khi nhận, 6 ngày với một số danh mục",
        "Người bán xem xét yêu cầu: trong 1 ngày theo lịch",
        "Người bán xem hàng trả về: trong 2 ngày theo lịch sau khi nhận",
        "Khiếu nại nếu cần: trong 7 ngày, 15 ngày với trả hàng tự sắp xếp",
      ];
      const rules = [
        ["Duyệt", "Yêu cầu hợp lệ thì duyệt sớm."],
        ["Từ chối kèm bằng chứng", "Chỉ khi có lý do hợp lệ, ví dụ video đóng gói."],
        ["Đề nghị hoàn một phần", "Khách chấp nhận thì đơn không tính vào SFRR."],
      ];
      return `${head("Một yêu cầu trả hàng, từng mốc thời gian")}
<div class="path">${path
        .map((p, i) => `<span class="crumb${i === 1 ? " crumb--ink" : ""}">${p}</span>`)
        .join(`<span class="sep">›</span>`)}</div>
<p class="label">Ở bước xem xét, người bán chọn một trong ba</p>
<div class="grid3">${rules
        .map(([t, d], i) => `<div class="box col">${num(i + 1)}<strong>${t}</strong><span class="desc">${d}</span></div>`)
        .join("")}</div>
<div class="result">Quá hạn ở bước xem xét yêu cầu hoặc xem hàng trả về: yêu cầu được tự động duyệt</div>`;
    },
  },
  {
    name: "ai-tra-phi-ship-v1",
    html: () => {
      const cases = [
        ["Lỗi người bán", "Gửi sai, hàng giả, thiếu bộ phận, sản phẩm lỗi, đóng gói kém, không khớp mô tả.", "Người bán chịu phí trả hàng.", true],
        ["Khách đổi ý", "Khách không còn muốn sản phẩm, hàng đủ điều kiện trả.", "Nền tảng trả phí trả hàng; người bán trả phí chiều đi đến mức trần, phần vượt nền tảng trả."],
        ["Lỗi kho vận", "Ví dụ kiện bị hỏng trong lúc vận chuyển.", "Đơn vị kho vận chịu phí trả hàng; hoa hồng nền tảng liên quan được hoàn cho người bán."],
        ["Giao không thành công", "Đơn bị hủy khi đang vận chuyển.", "Người bán chịu phí vận chuyển trả hàng."],
      ];
      return `${head("Ai trả phí ship khi hàng quay về")}
<div class="grid2">${cases
        .map(
          ([t, d, who, accent]) =>
            `<div class="box half${accent ? " box--accent" : ""}"><strong class="metric">${t}</strong><span class="desc">${d}</span><span class="label">Ai trả</span><span class="look">${who}</span></div>`,
        )
        .join("")}</div>
<p class="note">TikTok quyết định bên nào có lỗi dựa trên bằng chứng các bên gửi.</p>`;
    },
  },
  {
    name: "chi-phi-mot-don-hoan-v1",
    html: () => {
      const cases = [
        ["Khách đổi ý sau khi nhận", [["Phí xử lý đơn, không hoàn", "3.000 ₫"], ["Phí chiều đi người bán trả", "22.000 ₫"]], "25.000 ₫", "Không tính vào SFRR"],
        ["Không đúng mô tả, lỗi người bán", [["Phí xử lý đơn, không hoàn", "3.000 ₫"], ["Phí trả hàng người bán chịu", "22.000 ₫"]], "25.000 ₫", "Tính vào SFRR", true],
      ];
      return `${head("Chi phí ngoài tiền hàng của một đơn 200.000 ₫ bị trả", true)}
<div class="grid2">${cases
        .map(
          ([t, rows, total, sfrr, accent]) =>
            `<div class="box half${accent ? " box--accent" : ""}"><strong class="metric">${t}</strong><ul class="costs">${rows
              .map(([k, v]) => `<li><span>${k}</span><b>${v}</b></li>`)
              .join("")}<li class="costs-total"><span>Cộng</span><b>${total}</b></li></ul><span class="small">${sfrr}</span></div>`,
        )
        .join("")}</div>
<p class="note">Tiền hàng 200.000 ₫ hoàn cho khách; phần hoàn tiền không bị tính phí giao dịch. Hàng trả về đã mở có thể không bán lại được như hàng mới.</p>`;
    },
  },
  /* ————— P46-C2 (D56): phi-san-tiktok-shop-2026 ————— */
  {
    name: "phi-mot-don-200k-v1",
    html: () => {
      const rows = [
        ["Giá bán", "200.000 ₫", 0, 100, "ink"],
        ["Phí hoa hồng 14 %", "−28.000 ₫", 86, 14, "neg"],
        ["Phí giao dịch 6 %", "−13.200 ₫", 79.4, 6.6, "neg"],
        ["Phí xử lý đơn", "−3.000 ₫", 77.9, 1.5, "neg"],
        ["Còn lại sau phí sàn", "155.800 ₫", 0, 77.9, "ink"],
        ["Giá vốn, đóng gói", "−114.000 ₫", 20.9, 57, "neg"],
        ["Lãi trước quảng cáo, thuế", "41.800 ₫", 0, 20.9, "acc"],
      ];
      return `${head("Một đơn 200.000 ₫, phí suất mặc định, khách trả 20.000 ₫ ship", true)}
<div class="wf">${rows
        .map(
          ([label, value, left, width, kind]) =>
            `<div class="wrow${kind === "acc" ? " wrow--total" : ""}"><span class="blabel">${label}</span><span class="wtrack"><span class="wbar wbar--${kind}" style="left:${left}%;width:${width}%"></span></span><span class="bval">${value}</span></div>`,
        )
        .join("")}</div>
<p class="note">Phí giao dịch tính trên 220.000 ₫ vì ship khách trả nằm trong cơ sở tính. Ba khoản phí sàn cộng lại 44.200 ₫, tức 22,1 % giá bán.</p>`;
    },
  },
  {
    name: "gmv-den-tien-ve-v1",
    html: () => {
      const path = [
        "GMV: tổng tiền khách thanh toán, gồm cả đơn hủy và hoàn tiền",
        "Trừ đơn hủy và hoàn tiền",
        "Trừ phí sàn: hoa hồng, giao dịch, xử lý đơn, vận hành logistic nếu có",
        "Tiền thực nhận, theo từng đơn đã quyết toán",
      ];
      return `${head("Từ GMV đến tiền thực nhận")}
<div class="path">${path
        .map((p, i) => `<span class="crumb${i === path.length - 1 ? " crumb--ink" : ""}">${p}</span>`)
        .join(`<span class="sep">›</span>`)}</div>
<div class="grid2">
  <div class="box half"><strong>Đọc GMV để</strong><ul><li>Thấy nhu cầu của khách ngay trong ngày</li><li>Tìm luồng, sản phẩm, chỉ số đang kéo doanh thu xuống</li></ul></div>
  <div class="box half"><strong>Đọc tiền thực nhận để</strong><ul><li>Biết lãi thật sau phí và hoàn tiền</li><li>Lên kế hoạch nhập hàng, giá bán</li></ul></div>
</div>
<p class="note">Hoàn tiền được ghi vào lúc yêu cầu được xử lý, không phải ngày mua: tuần gần nhất thường trông ít hoàn hơn thực tế.</p>`;
    },
  },
  /* ————— P46-C1 (D56): khach-xem-nhung-khong-mua-tiktok-shop ————— */
  {
    name: "sau-cu-nhap-v1",
    html: () => {
      const path = ["Lượt nhấp vào sản phẩm", "Trang sản phẩm", "Giỏ hàng", "Thanh toán, thành đơn"];
      const steps = [
        ["Trang sản phẩm", "Tỷ lệ thêm vào giỏ hàng", ["Ảnh thật, kích thước, chất liệu", "Biến thể khách cần còn hàng", "Đánh giá, điểm xếp hạng", "Giá sau giảm so với sản phẩm tương tự"]],
        ["Giỏ hàng", "Từ giỏ đến đơn", ["Voucher khách thấy có áp dụng được không", "Giỏ đã đạt mức chi tối thiểu chưa"]],
        ["Thanh toán", "Từ giỏ đến đơn", ["Phí vận chuyển", "Tổng tiền cuối cùng khách phải trả"]],
      ];
      return `${head("Sau cú nhấp: khách đi qua ba chỗ trước khi thành đơn")}
<div class="path">${path
        .map((p, i) => `<span class="crumb${i === path.length - 1 ? " crumb--ink" : ""}">${p}</span>`)
        .join(`<span class="sep">›</span>`)}</div>
<div class="grid3 cards paths">${steps
        .map(
          ([t, metric, items], i) =>
            `<div class="box col">${num(i + 1)}<strong>${t}</strong><span class="label">${metric}</span><ul class="hang">${items.map((m) => `<li>${m}</li>`).join("")}</ul></div>`,
        )
        .join("")}</div>
<p class="note">CTOR = Đơn hàng SKU ÷ Lượt nhấp vào sản phẩm: nó gộp cả ba chỗ. Tỷ lệ thêm vào giỏ hàng tách chỗ đầu khỏi hai chỗ sau.</p>
<p class="small">Khách xem video hay LIVE có thể đặt ngay mà không qua giỏ, nên cách tách này rõ nhất ở Thẻ sản phẩm và Tab cửa hàng.</p>`;
    },
  },
  {
    name: "ctor-hai-luong-v1",
    html: () => `${head("Một sản phẩm, hai nguồn, cùng một trang sản phẩm", true)}
<div class="grid2">
  <div class="box option"><span class="label">Thẻ sản phẩm</span><strong>Khách tự tìm đến</strong><span class="eq">1.200 lượt nhấp · 60 đơn hàng SKU</span><strong class="res">CTOR 5 %</strong></div>
  <div class="box option box--accent"><span class="label">Video</span><strong>Khách đến từ một video</strong><span class="eq">800 lượt nhấp · 8 đơn hàng SKU</span><strong class="res">CTOR 1 %</strong></div>
</div>
<p class="formula">Gộp hai nguồn: 2.000 lượt nhấp, 68 đơn hàng SKU, CTOR 3,4 %</p>
<div class="result">Trang giữ được khách tự tìm đến: xem video hứa gì trước khi sửa trang</div>`,
  },
  {
    name: "ctor-trieu-chung-v1",
    html: () => {
      const rows = [
        ["Tỷ lệ thêm vào giỏ hàng thấp", "Trang sản phẩm chưa thuyết phục", ["Ảnh, mô tả thiếu kích thước, chất liệu, cách dùng", "Ít đánh giá, hoặc đánh giá mới bị chê", "Giá cao hơn sản phẩm tương tự (Chẩn đoán giá)"]],
        ["Thêm vào giỏ nhiều, ít đơn", "Vướng ở bước thanh toán", ["Phí vận chuyển", "Voucher hết hạn, hoặc giỏ chưa đạt mức chi tối thiểu", "Khách chờ một đợt giảm giá"]],
        ["CTOR thấp ở một nguồn, ổn ở nguồn khác", "Nội dung hứa khác trang", ["Giá, ưu đãi nói trong video, LIVE còn hiệu lực không", "Biến thể được giới thiệu có đúng biến thể trên trang"]],
        ["CTOR thấp ở mọi nguồn", "Vấn đề nằm ở chính trang", ["Sửa trang trước, chưa cần sửa nội dung", "Một thay đổi mỗi lần"]],
      ];
      return `${head("Triệu chứng sau cú nhấp, nghi phạm và việc cần xem")}
<div class="grid2">${rows
        .map(
          ([sign, step, checks], i) =>
            `<div class="box half"><div class="sect-head">${num(i + 1)}<strong>${sign}</strong></div><span class="metric">${step}</span><span class="label">Xem lại</span><ul class="hang">${checks.map((c) => `<li>${c}</li>`).join("")}</ul></div>`,
        )
        .join("")}</div>
<p class="note">So với chính sản phẩm đó ở kỳ trước và với sản phẩm khác của shop, trên cùng nguồn: TikTok không công bố một mức CTOR chuẩn chung.</p>`;
    },
  },
  /* ————— P46-C1 (D56): tang-gia-tri-don-hang-trung-binh-tiktok-shop ————— */
  {
    name: "aov-hai-shop-v1",
    html: () => `${head("Cùng GMV, hai cách đi đến đó", true)}
<div class="chain"><span class="chip">Lượt hiển thị</span><span class="x">×</span><span class="chip">CTR</span><span class="x">×</span><span class="chip">CTOR</span><span class="x">×</span><span class="chip chip--ink">AOV</span><span class="x">=</span><span class="chip">GMV</span></div>
<div class="grid2">
  <div class="box option"><span class="label">Shop A</span><strong>Nhiều đơn nhỏ</strong><span class="eq">1.000 đơn × 60.000 ₫</span><strong class="res">60.000.000 ₫</strong><span class="small">Phí xử lý đơn: 1.000 × 3.000 ₫ = 3.000.000 ₫</span></div>
  <div class="box option box--accent"><span class="label">Shop B</span><strong>Ít đơn hơn, mỗi đơn lớn hơn</strong><span class="eq">400 đơn × 150.000 ₫</span><strong class="res">60.000.000 ₫</strong><span class="small">Phí xử lý đơn: 400 × 3.000 ₫ = 1.200.000 ₫</span></div>
</div>
<div class="result">Cùng GMV, shop A cần gấp 2,5 lần số đơn và trả gấp 2,5 lần phí xử lý đơn</div>`,
  },
  {
    name: "aov-phi-co-dinh-v1",
    html: () => {
      const rows = [
        ["Đơn 50.000 ₫", "6 %", 100],
        ["Đơn 100.000 ₫", "3 %", 50],
        ["Đơn 200.000 ₫", "1,5 %", 25],
        ["Đơn 400.000 ₫", "0,75 %", 12.5],
      ];
      return `${head("Phí xử lý đơn 3.000 ₫ chiếm bao nhiêu phần giá trị đơn", true)}
<div class="bars">${rows
        .map(
          ([label, pct, w]) =>
            `<div class="brow"><span class="blabel">${label}</span><div class="track"><div class="bar bar--ink bar--full" style="left:0;width:${w}%"></div></div><span class="bval">${pct}</span></div>`,
        )
        .join("")}</div>
<p class="note">Theo Học viện TikTok Shop (bài Phí Xử Lý Đơn Hàng): 3.000 đồng cố định cho mỗi đơn giao thành công, đã gồm thuế, với mọi giá trị đơn và số lượng hàng trong đơn.</p>
<p class="small">Chỉ tính phí xử lý đơn hàng. Các khoản phí và chi phí khác chưa có trong hình.</p>`;
    },
  },
  {
    name: "aov-cong-cu-v1",
    html: () => {
      const tools = [
        ["Voucher thông thường", "Giảm theo số tiền hoặc phần trăm khi giỏ đạt mức chi tối thiểu.", ["Mẹo của TikTok: mức chi tối thiểu cao hơn 1,2 đến 1,5 lần AOV", "Mỗi đơn chỉ dùng một voucher của nhà bán hàng"]],
        ["Mua Sỉ Giá Hời", "Mua đủ số lượng thì được giảm phần trăm.", ["Tối đa hai bậc", "Hợp với hàng mua nhiều cái, nhiều màu"]],
        ["Ưu đãi theo gói", "Hai đến ba sản phẩm mua cùng nhau, giá cố định hoặc phần trăm giảm.", ["Giá ưu đãi của từng SKU phải thấp hơn giá gốc", "Không cộng dồn với Mua Sỉ Giá Hời"]],
        ["Quà tặng khi mua hàng", "Mua đủ số món hoặc chi đủ mức thì được quà.", ["Không giảm giá trực tiếp", "Khách trả phí vận chuyển cả quà: chọn quà nhẹ"]],
      ];
      return `${head("Bốn công cụ khuyến mãi TikTok mô tả là để tăng giá trị đơn")}
<div class="grid2">${tools
        .map(
          ([t, d, items]) =>
            `<div class="box half"><strong>${t}</strong><span class="desc">${d}</span><ul class="hang">${items.map((m) => `<li>${m}</li>`).join("")}</ul></div>`,
        )
        .join("")}</div>
<p class="note">Cả bốn do nhà bán hàng trợ giá và tự tạo trong Trung tâm nhà bán hàng. Tóm tắt từ Học viện TikTok Shop, kiểm tra 17/10/2026.</p>`;
    },
  },
  {
    name: "aov-cong-don-v1",
    html: () => {
      const path = ["Giá sản phẩm: chỉ một mức có hiệu lực", "Khuyến mãi cấp giỏ hàng", "Voucher: một voucher mỗi đơn", "Giá khách trả"];
      const rows = [
        ["Hai sản phẩm, giá gốc 100.000 ₫ mỗi cái", "200.000 ₫"],
        ["Giảm giá sản phẩm còn 90.000 ₫ mỗi cái", "180.000 ₫"],
        ["Mua Sỉ Giá Hời: mua 2 giảm 10 %", "162.000 ₫"],
        ["Voucher: chi tối thiểu 150.000 ₫, giảm 15.000 ₫", "147.000 ₫"],
      ];
      return `${head("Khuyến mãi cộng dồn theo ba lớp", true)}
<div class="path">${path
        .map((p, i) => `<span class="crumb${i === path.length - 1 ? " crumb--ink" : ""}">${p}</span>`)
        .join(`<span class="sep">›</span>`)}</div>
<div class="box ledger">${rows.map(([t, v]) => `<div class="lrow"><span>${t.replace(/ (₫|%)/g, "&nbsp;$1")}</span><strong>${v}</strong></div>`).join("")}</div>
<div class="result">Ba lớp cộng lại: khách trả 147.000 ₫ cho 200.000 ₫ giá gốc, tức giảm 26,5 %</div>
<p class="small">Theo Học viện TikTok Shop (bài Cách Tính Khuyến Mãi Cộng Dồn): các lớp khác nhau cộng dồn được; mức chi tối thiểu của voucher xét trên giá sau giảm giá sản phẩm.</p>`;
    },
  },
  /* ————— P46-D2 (D56): mo-ta-san-pham-tiktok-shop ————— */
  {
    name: "mo-ta-nam-nhom-cau-hoi-v1",
    html: () => {
      const groups = [
        ["Kích thước, biến thể", "“Cao 1m60, nặng 50kg mặc size nào?”", "“Chai này bao nhiêu ml?”", "Thông số, bảng kích cỡ"],
        ["Chất liệu, thành phần", "“Vải có co giãn không?”", "“Có cồn, có hương liệu không?”", "Thông số, thành phần chính"],
        ["Cách dùng, bảo quản", "“Giặt máy được không?”", "“Thoa trước hay sau kem dưỡng?”", "Cách dùng, lưu ý an toàn"],
        ["Trong hộp có gì", "“Có kèm thắt lưng không?”", "“Mua 1 hay cả bộ 3 chai?”", "Trong hộp có gì"],
        ["Giao nhận, đổi trả", "“Không vừa có đổi size được không?”", "“Hết hạn khi nào?”", "Chính sách của shop, hạn sử dụng"],
      ];
      return `${head("Năm nhóm câu hỏi lặp lại và chỗ trả lời trong mô tả", true)}
<div class="grid2">${groups
        .map(
          ([t, fashion, beauty, where], i) =>
            `<div class="box half"><div class="sect-head">${num(i + 1)}<strong>${t}</strong></div><span class="label">Thời trang</span><span class="desc">${fashion}</span><span class="label">Mỹ phẩm</span><span class="desc">${beauty}</span><span class="metric">Trả lời ở: ${where}</span></div>`,
        )
        .join("")}<div class="box half box--accent"><strong>Chưa cần vào mô tả</strong><ul class="hang"><li>Câu chỉ một người hỏi trong cả tuần</li><li>Câu về giá, mã giảm giá, phí vận chuyển</li><li>Câu về điều video hay LIVE đã hứa</li></ul></div></div>
<p class="note">Gom câu hỏi từ tin nhắn, bình luận video và LIVE, đánh giá và lý do trả hàng trong 7 ngày; giữ năm câu nhiều nhất cho mỗi sản phẩm.</p>`;
    },
  },
  {
    name: "mo-ta-truoc-sau-v1",
    html: () => {
      const after = [
        ["Mở đầu", "Kem chống nắng dạng sữa cho da dầu, dùng hằng ngày dưới lớp trang điểm.", true],
        ["Thông số", "Dung tích 50 ml. Thành phần chính ghi trên nhãn. Xuất xứ ghi trên bao bì.", true],
        ["Cách dùng", "Thoa sau kem dưỡng, trước trang điểm. Thoa lại sau khi ra mồ hôi nhiều.", true],
        ["Lưu ý", "Tránh vùng mắt. Ngưng dùng nếu kích ứng. Bảo quản nơi khô, tránh nắng.", false],
        ["Trong hộp có gì", "1 tuýp 50 ml, không kèm quà tặng.", true],
      ];
      return `${head("Một mô tả trước và sau khi trả lời câu hỏi lặp lại", true)}
<div class="grid2"><div class="box half"><span class="label">Trước</span><span class="desc">Kem chống nắng thấm nhanh, không bết, ai dùng cũng thích. Giá tốt, mua ngay!</span><span class="label">Khách vẫn hỏi</span><ul class="hang"><li>Da dầu dùng được không?</li><li>Tuýp bao nhiêu ml?</li><li>Thoa trước hay sau kem dưỡng?</li><li>Có kèm quà không?</li></ul></div><div class="box half box--accent"><span class="label">Sau</span><ul class="costs">${after
        .map(([k, v, added]) => `<li><span><b>${k}</b><br>${v}</span>${added ? `<b class="metric">Trả lời 1 câu hỏi</b>` : ""}</li>`)
        .join("")}</ul></div></div>
<p class="note">Bản sau bỏ câu “ai dùng cũng thích” vì không kiểm chứng được, và đưa câu trả lời cho câu hỏi hay gặp nhất lên dòng đầu.</p>`;
    },
  },
  {
    name: "mo-ta-duoc-khong-duoc-v1",
    html: () => {
      const yes = [
        "Đặc điểm chính: đặc tính, chức năng, thành phần, số lượng",
        "Độ dài không dưới 30 từ",
        "Thông tin an toàn, thông số kỹ thuật, cảnh báo",
        "Sản phẩm và tất cả phụ kiện đi kèm: trong hộp có gì",
        "Bảng kích cỡ có số đo và đơn vị với hàng thời trang",
        "Màu ngẫu nhiên thì nói rõ màu ngẫu nhiên",
      ];
      const no = [
        "“Số 1”, “tốt nhất”, “duy nhất”, “100% tự nhiên”, “ngay tức thì”, trừ khi chính xác và xác minh được",
        "So sánh với sản phẩm hoặc trang thương mại điện tử khác",
        "Giá khuyến mại phóng đại, giải thưởng hay chứng nhận không có",
        "Số điện thoại, Zalo, mạng xã hội, email, đường dẫn, mã QR",
        "Thông tin không khớp tiêu đề, ảnh, thuộc tính hay hàng thật",
      ];
      return `${head("Trong mô tả sản phẩm: nên có và không được")}
<div class="grid2"><div class="box half box--accent"><strong class="metric">Nên có, theo chính sách</strong><ul class="hang">${yes.map((m) => `<li>${m}</li>`).join("")}</ul></div><div class="box half"><strong>Không được</strong><ul class="hang">${no.map((m) => `<li>${m}</li>`).join("")}</ul></div></div>
<p class="small">Tóm tắt từ Trung tâm chính sách TikTok Shop: Tiêu đề, mô tả, hình ảnh và video về sản phẩm; Hướng dẫn đăng bán sản phẩm; Mô tả sản phẩm phóng đại; Chuyển hướng truy cập; SNAD; Hướng dẫn bảng kích cỡ.</p>`;
    },
  },
  /* ————— P46-D2 (D56): quy-dinh-livestream-ban-hang ————— */
  {
    name: "livestream-ba-vai-v1",
    html: () => {
      const roles = [
        ["Nền tảng", "Luật Thương mại điện tử, Điều 22, và nghị định hướng dẫn", ["Công khai quy chế livestream", "Nhận, giải quyết khiếu nại của người xem trong và sau buổi phát", "Công cụ hiển thị cảnh báo hàng có nguy cơ mất an toàn", "Xác thực điện tử danh tính người livestream", "Dừng phát, gỡ nội dung vi phạm", "Lưu hình ảnh, âm thanh ít nhất 01 năm"]],
        ["Người bán", "Luật Thương mại điện tử, Điều 23", ["Đưa giấy tờ điều kiện kinh doanh và chất lượng hàng cho người livestream trước buổi phát", "Đưa văn bản xác nhận nội dung quảng cáo cho nền tảng và người livestream khi luật yêu cầu", "Nội dung bán hàng khớp nội dung đã xác nhận", "Dừng hợp tác, gỡ thông tin khi có vi phạm"], true],
        ["Người livestream", "Luật Thương mại điện tử, Điều 24", ["Cung cấp thông tin để xác thực danh tính", "Làm theo quy chế livestream của nền tảng", "Từ chối khi người bán không đưa đủ giấy tờ", "Không nói gian dối về công dụng, xuất xứ, chất lượng, giá, khuyến mại, bảo hành", "Không trái đạo đức xã hội, thuần phong mỹ tục"]],
      ];
      return `${head("Ba vai trong một buổi livestream bán hàng")}
<div class="grid3">${roles
        .map(
          ([t, law, items, accent]) =>
            `<div class="box col${accent ? " box--accent" : ""}"><strong>${t}</strong><span class="small">${law}</span><ul class="hang">${items.map((m) => `<li>${m}</li>`).join("")}</ul></div>`,
        )
        .join("")}</div>
<div class="result">Người bán đưa giấy tờ, người livestream nói đúng, nền tảng lưu và xử lý khiếu nại</div>`;
    },
  },
  {
    name: "livestream-luat-va-tiktok-v1",
    html: () => {
      const law = [
        "Livestream bán hàng có định nghĩa và trách nhiệm riêng cho nền tảng, người bán, người livestream",
        "Văn bản xác nhận nội dung quảng cáo với hàng luật yêu cầu",
        "Nền tảng xác thực điện tử danh tính người bán và người livestream",
        "Người có ảnh hưởng thông báo quảng cáo, kiểm tra tài liệu, không giới thiệu sản phẩm chưa dùng",
      ];
      const tiktok = [
        "Tải Giấy xác nhận nội dung quảng cáo cho thực phẩm, sữa và dinh dưỡng cho trẻ từ 36 tháng tuổi trở xuống; không có thì có thể bị hạn chế quảng bá trong LIVE",
        "Quét NFC trên CCCD gắn chip cho người bán mới; nhà sáng tạo xác minh NFC và cung cấp mã số thuế khi được yêu cầu",
        "Không phát cùng một phiên LIVE trên TikTok Shop và nền tảng khác cùng lúc",
        "Flash sale trên LIVE chạy bằng công cụ Flash Sale; không hứa voucher không có, không bịa nhầm giá",
      ];
      return `${head("Luật nói gì, TikTok Shop quy định thêm gì")}
<div class="grid2"><div class="box half"><strong>Luật và nghị định</strong><span class="small">Áp dụng cho mọi nền tảng</span><ul class="hang">${law.map((m) => `<li>${m}</li>`).join("")}</ul></div><div class="box half box--accent"><strong class="metric">Chính sách của TikTok Shop</strong><span class="small">Quy định của nền tảng, không phải của luật</span><ul class="hang">${tiktok.map((m) => `<li>${m}</li>`).join("")}</ul></div></div>
<p class="small">Theo các văn bản đăng trên Công báo Chính phủ và trang Cập nhật Chính sách mới nhất của TikTok Shop Việt Nam; ngày hiệu lực ghi trong bài.</p>`;
    },
  },
  /* ————— P46-D1 (D56): dat-ten-san-pham-tiktok-shop ————— */
  {
    name: "tieu-de-hai-viec-v1",
    html: () => `${head("Tiêu đề làm hai việc trên Thẻ sản phẩm")}
<div class="chain"><span class="chip chip--ink">Lượt hiển thị</span><span class="x">×</span><span class="chip chip--ink">CTR</span><span class="x">×</span><span class="chip">CTOR</span><span class="x">×</span><span class="chip">AOV</span><span class="x">=</span><span class="chip">GMV</span></div>
<div class="grid2">
  <div class="box half"><span class="label">Việc 1 · Lượt hiển thị</span><strong>Được tìm ra</strong><ul class="hang"><li>Có những từ người mua thật sự gõ khi tìm</li><li>Đúng loại sản phẩm, khớp ngành hàng và thuộc tính</li><li>Không lặp từ, không nhồi từ khóa không liên quan</li></ul></div>
  <div class="box half box--accent"><span class="label">Việc 2 · CTR</span><strong>Được hiểu ngay</strong><ul class="hang"><li>Nhìn là biết đây là gì, loại nào, bao nhiêu</li><li>Quy cách khớp với giá đang hiện trên thẻ</li><li>Phần đầu tiêu đề nói điều quan trọng nhất</li></ul></div>
</div>
<p class="note">Đọc hai chỉ số cùng lúc, trên riêng luồng Thẻ sản phẩm: tiêu đề mới có thể kéo thêm lượt hiển thị từ những người ít liên quan hơn, nên CTR giảm dù tiêu đề không kém đi.</p>`,
  },
  {
    name: "tieu-de-nam-thanh-phan-v1",
    html: () => {
      const rows = [
        ["Thương hiệu", "Chỉ khi được ủy quyền", "(không ghi, chưa được ủy quyền)", "Thương hiệu X"],
        ["Loại sản phẩm", "Nói ngay đây là gì", "Áo thun nam cổ tròn", "Sữa rửa mặt"],
        ["Chất liệu, thành phần chính", "Nếu có", "cotton", "trà xanh"],
        ["Đặc điểm chính", "Màu, chức năng, biến thể", "tay ngắn, đen / trắng / xám", "dạng gel"],
        ["Số lượng, quy cách", "Nêu đủ mọi tùy chọn", "size M / L / XL", "100 ml / 150 ml"],
      ];
      return `${head("Năm thành phần chính sách TikTok gợi ý cho tiêu đề", true)}
<div class="box tt">
  <div class="tt-row tt-head"><span>Thành phần</span><span>Thời trang</span><span>Mỹ phẩm</span></div>
  ${rows
    .map(
      ([part, rule, a, b]) =>
        `<div class="tt-row"><span class="tt-part"><strong>${part}</strong><em>${rule}</em></span><span class="tt-cell"><i class="only-m">Thời trang: </i>${a}</span><span class="tt-cell"><i class="only-m">Mỹ phẩm: </i>${b}</span></div>`,
    )
    .join("")}
</div>
<div class="grid2">
  <div class="box option"><span class="label">Tiêu đề thời trang · 71 ký tự</span><strong>Áo thun nam cổ tròn cotton tay ngắn, đen / trắng / xám, size M / L / XL</strong></div>
  <div class="box option box--accent"><span class="label">Tiêu đề mỹ phẩm · 59 ký tự</span><strong>Sữa rửa mặt trà xanh dạng gel Thương hiệu X 100 ml / 150 ml</strong></div>
</div>
<p class="small">Thành phần theo trang chính sách Tiêu đề, mô tả, hình ảnh và video về sản phẩm (23/04/2026). Hai sản phẩm và tên Thương hiệu X là giả định.</p>`;
    },
  },
  {
    name: "tieu-de-truoc-sau-v1",
    html: () => {
      const bad = [
        ["★ ★", "ký hiệu, ký tự đặc biệt"],
        ["SALE SỐC, FREESHIP", "khuyến mãi, không mô tả sản phẩm"],
        ["rẻ nhất", "khẳng định tuyệt đối không xác minh được"],
        ["Shop ABC", "tên người bán"],
        ["thiếu chất liệu, màu, size", "người mua không biết đang mua gì"],
      ];
      const good = ["Loại sản phẩm đứng đầu: Áo thun nam cổ tròn", "Chất liệu: cotton", "Đặc điểm: tay ngắn, ba màu", "Quy cách: đủ ba size"];
      return `${head("Một tiêu đề giả định, trước và sau khi viết lại", true)}
<div class="grid2">
  <div class="box half"><span class="label">Trước · 54 ký tự</span><strong class="tt-title">★ SALE SỐC ★ Áo thun nam đẹp rẻ nhất Shop ABC FREESHIP</strong><ul class="tt-flags">${bad
    .map(([w, why]) => `<li><b>${w}</b><span>${why}</span></li>`)
    .join("")}</ul></div>
  <div class="box half box--accent"><span class="label">Sau · 71 ký tự</span><strong class="tt-title">Áo thun nam cổ tròn cotton tay ngắn, đen / trắng / xám, size M / L / XL</strong><ul class="hang">${good
    .map((g) => `<li>${g}</li>`)
    .join("")}</ul><span class="small">Ưu đãi đặt bằng công cụ khuyến mãi, không viết vào tiêu đề.</span></div>
</div>
<div class="result">Bỏ những gì không mô tả sản phẩm, thêm những gì người mua cần để bấm</div>`;
    },
  },
  /* ————— P46-D1 (D56): anh-bia-san-pham-tiktok-shop ————— */
  {
    name: "anh-bia-tren-the-v1",
    html: () => {
      const card = (accent) =>
        `<div class="pcard${accent ? " pcard--accent" : ""}"><div class="pc-img">${accent ? num(1, true) : ""}</div><div class="pc-line" style="width:88%">${accent ? num(2) : ""}</div><div class="pc-line" style="width:60%"></div><div class="pc-price">${accent ? num(3) : ""}</div></div>`;
      const legend = [
        ["Hình ảnh chính", "Ảnh đầu tiên người dùng thấy, phần lớn nhất của thẻ. Nó quyết định người lướt có dừng lại và bấm không: đó là CTR."],
        ["Tiêu đề", "Trên thẻ nhỏ, phần cuối của tiêu đề dễ bị cắt."],
        ["Giá", "Người mua đọc giá cùng với ảnh: ảnh 1 chai cạnh giá của 3 chai trông như đắt gấp ba."],
      ];
      return `${head("Trên trang tìm kiếm, hình ảnh chính là thứ người mua thấy trước tiên")}
<div class="pc-wrap">
  <div class="pcards">${card(true)}${card(false)}${card(false)}${card(false)}</div>
  <div class="pc-legend">${legend
    .map(([t, d], i) => `<div class="step">${num(i + 1, i === 0)}<div><strong>${t}</strong><span>${d}</span></div></div>`)
    .join("")}
    <div class="box vv"><div><strong>Ảnh thứ 2 đến 9 và video</strong></div><span class="desc">Chỉ thấy sau khi bấm vào trang sản phẩm: chúng tác động đến CTOR.</span></div>
  </div>
</div>
<p class="note">“Ảnh bìa” ở đây là hình ảnh chính của thẻ sản phẩm, không phải ảnh bìa của một video TikTok. Hình vẽ minh họa, không phải giao diện thật.</p>`;
    },
  },
  {
    name: "anh-bia-ba-phuong-an-v1",
    html: () => {
      const bottles = (n, h, w) =>
        Array.from({ length: n }, () => `<div class="btl" style="height:${h}%;width:${w}%"><div class="btl-cap"></div></div>`).join("");
      const options = [
        ["A", "Một chai, nhỏ giữa khung", bottles(1, 34, 13), "", "Chưa đạt", "Sản phẩm dưới 60 % khung, và khách tưởng giá trên thẻ là của một chai."],
        ["B", "Đủ ba chai, chiếm gần hết khung", bottles(3, 74, 18), "", "Đúng yêu cầu", "Nền trắng, thấy toàn bộ, cho thấy đúng quy cách đang bán.", true],
        ["C", "Ba chai, dải chữ khuyến mãi phía trước", bottles(3, 74, 18), `<div class="banner">GIẢM 50 %</div>`, "Không nên", "Chữ che phía trước sản phẩm, và thành sai khi đợt giảm giá kết thúc."],
      ];
      return `${head("Ba phương án hình ảnh chính cho một combo 3 chai dầu gội", true)}
<div class="grid3 cards">${options
        .map(
          ([k, t, art, over, verdict, why, ok]) =>
            `<div class="box col${ok ? " box--accent" : ""}"><div class="shot">${art}${over}</div><strong>${k}. ${t}</strong><span class="metric">${verdict}</span><span class="desc">${why}</span></div>`,
        )
        .join("")}</div>
<div class="result">Lọc theo yêu cầu trước; kiểu ảnh nào được bấm nhiều hơn thì chỉ số của shop bạn mới trả lời được</div>`;
    },
  },
  {
    name: "anh-bia-doi-chung-v1",
    html: () => {
      const path = ["14 ngày trước: mốc so sánh", "Ngày bạn thay ảnh: ghi lại ngày này", "Ngày 7: đọc sơ bộ", "Ngày 14: chốt kết quả"];
      const rows = [
        ["Sản phẩm đổi ảnh", "2,0 % → 2,6 %", 90, "+30 %", true],
        ["Nhóm không đổi", "2,0 % → 2,2 %", 30, "+10 %"],
      ];
      return `${head("Đọc CTR Thẻ sản phẩm sau khi đổi ảnh: so với nhóm không đổi", true)}
<div class="path">${path
        .map((p, i) => `<span class="crumb${i === path.length - 1 ? " crumb--ink" : ""}">${p}</span>`)
        .join(`<span class="sep">›</span>`)}</div>
<div class="bars">${rows
        .map(
          ([label, change, w, pct, accent]) =>
            `<div class="brow"><span class="blabel">${label}</span><div class="track"><div class="bar ${accent ? "bar--acc" : "bar--ink"} bar--full" style="left:0;width:${w}%"></div></div><span class="bval">${pct}<em>CTR ${change}</em></span></div>`,
        )
        .join("")}</div>
<div class="result">Phần có thể gán cho ảnh mới: khoảng 18 % (1,30 ÷ 1,10), không phải 30 %</div>
<p class="small">Cả shop cùng tăng 10 % trong hai tuần đó, có thể do một đợt sale. Chỉ phần vượt lên trên nhóm không đổi mới là của ảnh.</p>`;
    },
  },
  /* ————— P46-E (D56): do-hieu-qua-sau-khi-sua-san-pham-tiktok-shop ————— */
  {
    name: "do-lich-14-ngay-v2",
    html: () => {
      const items = [
        ["seg seg--base", 1, "14 ngày trước khi sửa", "Mốc so sánh, chốt cố định từ ngày sửa"],
        ["mark", 1, "Ngày sửa", "Ghi ngày, giá, khuyến mãi, nội dung trang, mức mong đợi"],
        ["seg", 2, "Ngày 1 đến 7", "Không sửa thêm gì trên sản phẩm này"],
        ["mark", 2, "Ngày 7", "Sơ bộ: đang lên, đi ngang hay đang giảm"],
        ["seg", 3, "Ngày 8 đến 14", "Vẫn không sửa thêm"],
        ["mark mark--ink", 3, "Ngày 14", "Chốt: giữ, đo thêm, sửa tiếp hay quay lại bản cũ"],
      ];
      const rules = [
        ["Trung bình mỗi ngày", "Hai khoảng dài bằng nhau, so bằng số trung bình mỗi ngày."],
        ["Một chỉ số mục tiêu", "Chỉ số mà thay đổi nhắm tới, trên đúng luồng nó tác động."],
        ["Chỉ số khác giữ ổn định", "Các chỉ số còn lại không được lệch quá mức dao động bình thường."],
      ];
      return `${head("Lịch đo một thay đổi")}
<div class="tl">${items
        .map(([cls, col, t, d]) => `<div class="${cls}" style="--c:${col}"><strong>${t}</strong><span>${d}</span></div>`)
        .join("")}</div>
<div class="grid3">${rules
        .map(([t, d], i) => `<div class="box col">${num(i + 1)}<strong>${t}</strong><span class="desc">${d}</span></div>`)
        .join("")}</div>`;
    },
  },
  {
    name: "do-doc-sai-doc-dung-v2",
    html: () => {
      const before = [4, 3, 5, 4, 6, 3, 4, 5, 3, 4, 6, 4, 3, 4];
      const after = [5, 3, 6, 4, 5, 6, 4, 5, 6, 4, 5, 7, 4, 5];
      const max = 7;
      const bars = (values, cls, mark = []) =>
        values
          .map((v, i) => `<i class="dbar ${cls}${mark.includes(i) ? " dbar--mark" : ""}" style="height:${(v / max) * 100}%"></i>`)
          .join("");
      const avgLine = (avg) => `<span class="avg" style="bottom:${(avg / max) * 100}%"></span>`;
      return `${head("Số đơn mỗi ngày của một sản phẩm, 14 ngày trước và 14 ngày sau khi sửa", true)}
<div class="dchart">
  <div class="dgroup">${bars(before, "dbar--base")}${avgLine(58 / 14)}</div>
  <div class="dsplit"><span>Ngày sửa</span></div>
  <div class="dgroup">${bars(after, "dbar--after", [1, 2])}${avgLine(69 / 14)}</div>
</div>
<div class="dlabels"><span>14 ngày trước: trung bình 4,1 đơn mỗi ngày</span><span>14 ngày sau: trung bình 4,9 đơn mỗi ngày</span></div>
<div class="grid2">
  <div class="box half"><span class="label">Đọc sai</span><strong>“Ngày 2 có 3 đơn, ngày 3 có 6 đơn: tăng gấp đôi”</strong><span class="desc">Hai ngày lẻ nằm trong dao động thường ngày của sản phẩm.</span></div>
  <div class="box half box--accent"><span class="label">Đọc đúng</span><strong>Tăng 0,8 đơn mỗi ngày, so hai trung bình 14 ngày</strong><span class="desc">Chưa vượt hẳn dao động thường ngày của sản phẩm: có thể đã thay đổi, chưa chắc chắn.</span></div>
</div>`;
    },
  },
  {
    name: "do-ba-ket-qua-v3",
    html: () => {
      const cards = [
        ["Giữ thay đổi", "Sản phẩm A", "2,0 % → 2,6 %", "Chạm mức mong đợi 2,5 %", "Vượt hẳn mức dao động: rõ", "GMV giữ được", true],
        ["Giữ, đo thêm 14 ngày", "Sản phẩm B", "2,0 % → 2,5 %", "Chạm mức mong đợi 2,5 %", "Chỉ nhỉnh hơn dao động: có thể", "GMV giữ được"],
        ["Giữ, sửa tiếp cùng hướng", "Sản phẩm C", "2,0 % → 2,3 %", "Chưa chạm mức mong đợi 2,5 %", "Vượt hẳn mức dao động: rõ", "GMV giữ được"],
        ["Quay lại bản cũ", "Sản phẩm D", "2,0 % → 2,1 %", "Chưa chạm mức mong đợi 2,5 %", "Nằm trong mức dao động", "GMV giữ được"],
      ];
      return `${head("Bốn kết quả ngày 14, cùng chỉ số mục tiêu CTR Thẻ sản phẩm", true)}
<div class="grid2">${cards
        .map(
          ([verdict, product, move, target, strength, gmv, accent]) =>
            `<div class="box half${accent ? " box--accent" : ""}"><span class="label">${product}</span><strong class="metric">${verdict}</strong><span class="eq">CTR ${move}</span><ul class="hang"><li>${target}</li><li>${strength}</li><li>${gmv}</li></ul></div>`,
        )
        .join("")}</div>
<p class="note">Đừng đọc một kết quả yếu thành mạnh hơn. Nếu trong 14 ngày có thay đổi khác trên sản phẩm, kết quả không dùng được để quyết định: đo lại từ đầu.</p>`;
    },
  },
  {
    name: "do-cua-so-sale-v1",
    html: () => {
      const rows = [
        ["Mốc so sánh chứa ngày sale", [8, 9, 10, 11], "Mốc bị đẩy lên: thay đổi dễ trông như thất bại"],
        ["Thời gian đo chứa ngày sale", [20, 21, 22, 23], "Số sau khi sửa bị đẩy lên: thay đổi dễ trông như thành công"],
        ["Cả hai khoảng đều là ngày thường", [], "So được với nhau", true],
      ];
      const cells = (sale) =>
        Array.from({ length: 28 }, (_, i) => {
          const cls = sale.includes(i) ? "cell--sale" : i < 14 ? "cell--base" : "cell--after";
          return `<i class="cell ${cls}${i === 14 ? " cell--start" : ""}"></i>`;
        }).join("");
      return `${head("Ngày sale nằm ở đâu so với hai khoảng 14 ngày")}
<div class="legend"><span><i class="sw sw--base"></i>14 ngày trước khi sửa</span><span><i class="sw sw--after"></i>14 ngày sau khi sửa</span><span><i class="sw sw--sale"></i>Ngày sale</span></div>
<div class="wins">${rows
        .map(
          ([t, sale, verdict, ok]) =>
            `<div class="win${ok ? " win--ok" : ""}"><strong>${t}</strong><div class="cells">${cells(sale)}</div><span class="verdict">${verdict}</span></div>`,
        )
        .join("")}</div>
<div class="result">Sửa khi cả 14 ngày trước và 14 ngày sau đều không có đợt sale lớn</div>`;
    },
  },
  /* ————— P46-E (D56): doanh-thu-sau-sale-tiktok-shop ————— */
  {
    name: "sale-ba-pha-v1",
    html: () => {
      const before = [9.6, 10.2, 9.8, 10.5, 10.9, 9.4, 9.7, 10.1, 9.9, 10.4, 10.8, 9.5, 9.6, 9.6];
      const during = [14.2, 15.1, 16.0, 16.8, 17.5, 17.0, 18.2, 19.4, 26.5, 20.3, 19.1, 20.4, 20.0];
      const after = [7.2, 7.8, 8.0, 8.3, 8.6, 8.9, 8.5, 9.4, 9.6, 9.9, 10.1, 9.8, 10.3, 10.0];
      const max = 27;
      const bars = (values, cls) =>
        values.map((v) => `<i class="dbar ${cls}" style="height:${(v / max) * 100}%"></i>`).join("");
      const phases = [
        ["Trước đợt sale", "14 ngày làm mốc", "10,0 triệu ₫"],
        ["Trong đợt sale", "13 ngày", "18,5 triệu ₫", true],
        ["7 ngày đầu sau đợt", "dưới mốc", "8,2 triệu ₫"],
        ["Ngày 8 đến 14 sau đợt", "gần về mốc", "9,9 triệu ₫"],
      ];
      return `${head("GMV mỗi ngày của một shop quanh một đợt sale", true)}
<div class="pchart">
  <div class="pgroup">${bars(before, "dbar--base")}<span class="avg" style="bottom:${(10 / max) * 100}%"></span></div>
  <div class="pgroup pgroup--sale">${bars(during, "dbar--sale")}</div>
  <div class="pgroup">${bars(after, "dbar--after")}<span class="avg avg--ref" style="bottom:${(10 / max) * 100}%"></span></div>
</div>
<div class="phases">${phases
        .map(
          ([t, d, v, accent]) =>
            `<div class="box phase${accent ? " box--accent" : ""}"><span class="label">${t}</span><strong>${v}</strong><span class="small">trung bình mỗi ngày, ${d}</span></div>`,
        )
        .join("")}</div>
<p class="note">Đường gạch ngang là mức trung bình của 14 ngày trước đợt. Đọc trung bình cả đợt, không đọc riêng ngày cao nhất.</p>`;
    },
  },
  {
    name: "sale-ghi-truoc-v1",
    html: () => {
      const groups = [
        ["Trước ngày bắt đầu", ["Trung bình mỗi ngày của 14 ngày gần nhất, theo luồng", "Giá, khuyến mãi đang chạy của từng sản phẩm", "Danh sách sản phẩm tham gia đợt sale", "Tồn kho của các biến thể bán chạy"]],
        ["Trong đợt", ["GMV theo luồng, mỗi ngày", "Ngày nào, sản phẩm nào hết hàng", "Không sửa tiêu đề, ảnh, mô tả để thử"]],
        ["7 ngày đầu sau đợt", ["Đơn hủy, yêu cầu trả hàng", "Luồng nào về dưới mốc", "Chưa kết luận gì"]],
        ["Ngày 14 sau đợt", ["So với mốc trước đợt", "Chia sản phẩm thành ba nhóm", "Chọn một thay đổi đầu tiên để đo"]],
      ];
      let n = 0;
      return `${head("Ghi gì, vào lúc nào")}
<div class="grid2 checklist">${groups
        .map(
          ([title, items], i) =>
            `<div class="box col${i === 0 ? " box--accent" : ""}"><strong>${title}</strong><ul class="checks">${items
              .map((item) => `<li><span class="check">${++n}</span>${item}</li>`)
              .join("")}</ul></div>`,
        )
        .join("")}</div>`;
    },
  },
  {
    name: "sale-theo-luong-v1",
    html: () => {
      const rows = [
        ["Thẻ sản phẩm", "4,0", "6,5", "3,5", "−12 %"],
        ["Tab cửa hàng", "1,0", "2,4", "0,9", "−10 %"],
        ["Video", "2,5", "4,0", "2,3", "−8 %"],
        ["LIVE", "1,5", "4,0", "0,7", "−53 %", true],
        ["Liên kết", "1,0", "1,6", "0,8", "−20 %"],
      ];
      const row = ([label, b, d, a, pct, accent], cls = "") =>
        `<div class="trow${cls}${accent ? " trow--accent" : ""}"><span class="tlabel">${label}</span><span><em>Trước</em>${b}</span><span><em>Trong</em>${d}</span><span><em>7 ngày sau</em>${a}</span><span class="tpct"><em>So với mốc</em>${pct}</span></div>`;
      return `${head("GMV mỗi ngày theo luồng, triệu ₫", true)}
<div class="ttable">
  <div class="trow trow--head"><span class="tlabel"></span><span>Trước đợt</span><span>Trong đợt</span><span>7 ngày sau</span><span>So với mốc</span></div>
  ${rows.map((r) => row(r)).join("")}
  ${row(["Toàn shop", "10,0", "18,5", "8,2", "−18 %"], " trow--total")}
</div>
<p class="note">Gần một nửa mức tụt (0,8 trong 1,8 triệu ₫ mỗi ngày) nằm ở LIVE: xem lịch LIVE sau đợt trước khi sửa trang sản phẩm.</p>`;
    },
  },
  {
    name: "sale-ba-nhom-v1",
    html: () => {
      const groups = [
        ["Giữ nhịp", "1,0 → 2,2 → 1,2 triệu ₫", "CTR và CTOR sau đợt cao hơn mốc", "Giữ nguyên, ưu tiên cho đợt sale sau"],
        ["Về mốc cũ", "1,0 → 2,0 → 1,0 triệu ₫", "Bán thêm nhờ ưu đãi, rồi về như trước", "Không cần sửa gấp"],
        ["Dưới mốc cũ", "1,0 → 1,8 → 0,7 triệu ₫", "Thấp hơn cả trước đợt", "Kiểm tra hủy, hoàn, hết hàng, giá đã về chưa", true],
      ];
      return `${head("Ba nhóm sản phẩm sau đợt sale", true)}
<p class="small">GMV mỗi ngày: trước đợt → trong đợt → ngày 8 đến 14 sau đợt</p>
<div class="grid3">${groups
        .map(
          ([t, v, d, act, accent]) =>
            `<div class="box half${accent ? " box--accent" : ""}"><strong class="metric">${t}</strong><span class="eq">${v}</span><span class="desc">${d}</span><span class="look"><b>Làm gì:</b> ${act}</span></div>`,
        )
        .join("")}</div>`;
    },
  },
  {
    name: "sale-gmv-con-lai-v1",
    html: () => {
      const rows = [
        ["GMV trong đợt sale, gồm cả đơn hủy và hoàn tiền", "100.000.000 ₫"],
        ["Đơn hủy trước khi giao", "−6.000.000 ₫"],
        ["Trả hàng, hoàn tiền ghi nhận sau đợt", "−4.000.000 ₫"],
        ["Tiền hàng còn lại, trước phí", "90.000.000 ₫"],
      ];
      return `${head("GMV của đợt sale và phần còn lại", true)}
<div class="box ledger">${rows.map(([t, v]) => `<div class="lrow"><span>${t}</span><strong>${v}</strong></div>`).join("")}</div>
<p class="note">Từ phần còn lại mới trừ phí sàn và phí xử lý đơn, khoản tính theo từng đơn giao thành công. Hoàn tiền thường ghi nhận sau ngày mua, nên con số này chỉ rõ sau vài tuần.</p>`;
    },
  },
];

function pageHtml(diagram, t, layout) {
  return `<!doctype html><html lang="vi"><head><meta charset="utf-8"><style>
${fontFaces()}
*{box-sizing:border-box;margin:0;padding:0}
html{-webkit-font-smoothing:antialiased}
body{background:${t.alt};font-family:"Be Vietnam Pro",sans-serif;color:${t.ink};font-size:15px;line-height:1.45}
.fig{padding:28px;display:flex;flex-direction:column;gap:18px}
.m .fig{padding:18px 16px;gap:14px;font-size:14px}
ul{list-style:none}
strong{font-weight:600}
.head{display:flex;flex-wrap:wrap;align-items:center;gap:8px 12px}
.title{font-size:17px;font-weight:600;color:${t.ink}}
.m .title{font-size:16px}
.pill{display:inline-block;padding:3px 10px;border:1px solid ${t["pink-line"]};border-radius:999px;background:${t["pink-tint"]};color:${t["pink-text"]};font-size:13px;font-weight:600}
.box{background:${t.bg};border:1px solid ${t.hairline};border-radius:12px;padding:12px 14px}
.box--accent{border-color:${t.pink};box-shadow:0 0 0 1px ${t.pink} inset;background:${t["pink-tint"]}}
.label{color:${t.muted};font-size:13px;font-weight:600}
.note{color:${t.body};font-size:14px}
.small{color:${t.muted};font-size:13px}
.num{flex:none;display:inline-flex;align-items:center;justify-content:center;width:26px;height:26px;border-radius:999px;background:${t.ink};color:${t.bg};font-size:13px;font-weight:600}
.num--accent{background:${t["pink-text"]}}
.result{padding:12px 16px;border-radius:12px;background:${t.ink};color:${t.bg};font-weight:600;text-align:center}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.grid3{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}
.m .grid2,.m .grid3{grid-template-columns:1fr;gap:10px}
.step{display:flex;gap:12px;align-items:flex-start}
.step div{display:flex;flex-direction:column;gap:3px}
.step div span{color:${t.body};font-size:14px}
.step--wide{grid-column:1/-1}
/* funnel */
.funnel{display:flex;flex-direction:column;align-items:center;gap:6px}
.stage{width:var(--w);display:flex;justify-content:space-between;gap:12px;padding:12px 16px;border:1px solid ${t.hairline};border-radius:12px;background:${t.bg}}
.m .stage{width:var(--wm);padding:10px 12px}
.stage span{color:${t.body}}
.stage--accent{border-color:${t.pink};box-shadow:0 0 0 1px ${t.pink} inset;background:${t["pink-tint"]}}
.stage--accent span{color:${t.ink};font-weight:600}
.op{color:${t["pink-text"]};font-weight:600;font-size:14px}
.formula{text-align:center;color:${t.ink};font-weight:500;font-size:14px;padding-top:2px}
/* streams */
.total{display:flex;flex-direction:column;align-items:center;gap:2px;margin:0 auto;padding:12px 22px;border-radius:12px;background:${t.ink};color:${t.bg}}
.total span{color:${t["chrome-dot"]};font-size:14px}
.bracket{height:14px;margin:-18px 10% 0;border:2px solid ${t["chrome-dot"]};border-bottom:0;border-radius:10px 10px 0 0;transform:translateY(14px)}
.m .bracket{display:none}
.streams{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:10px}
.m .streams{grid-template-columns:1fr}
.stream{display:flex;flex-direction:column;gap:4px;padding:12px}
.tag{align-self:flex-start;padding:1px 8px;border-radius:999px;background:${t.backdrop};color:${t.muted};font-size:12px;font-weight:600}
.from{color:${t.body};font-size:13px}
.formula-sm{margin-top:auto;padding-top:6px;color:${t["pink-text"]};font-size:12px;font-weight:500}
.m .stream{display:grid;grid-template-columns:auto 1fr;column-gap:10px;row-gap:2px;align-items:center}
.m .stream strong{grid-column:2;grid-row:1}
.m .stream .tag{grid-column:1;grid-row:1}
.m .stream .from,.m .stream .formula-sm{grid-column:1/-1}
.m .formula-sm{padding-top:0}
/* chain */
.chain{display:flex;flex-wrap:wrap;justify-content:center;align-items:center;gap:6px}
.chip{padding:6px 12px;border:1px solid ${t.hairline};border-radius:999px;background:${t.bg};font-weight:500;font-size:14px}
.m .chip{padding:5px 9px;font-size:13px}
.chip--ink{background:${t.ink};border-color:${t.ink};color:${t.bg}}
.x{color:${t["pink-text"]};font-weight:600}
.col{display:flex;flex-direction:column;gap:6px}
.col .num{margin-bottom:2px}
.metric{color:${t["pink-text"]};font-weight:600}
.col ul{display:flex;flex-direction:column;gap:3px;color:${t.body};font-size:14px}
.col ul:not(.checks) li::before,.half ul li::before{content:"";display:inline-block;width:6px;height:6px;margin-right:8px;border-radius:999px;background:${t.pink};vertical-align:middle}
.m .col{display:grid;grid-template-columns:auto 1fr;column-gap:10px;row-gap:4px;align-items:center}
.m .col>*{grid-column:2}
.m .col .num{grid-column:1;grid-row:1;margin:0}
.m .col>strong{grid-row:1}
/* flow */
.flow{display:flex;align-items:center;gap:0}
.node{flex:1;text-align:center;font-weight:600;padding:12px 10px}
.node--ink{background:${t.ink};border-color:${t.ink};color:${t.bg}}
.arrow{flex:none;width:118px;position:relative;text-align:center;padding-bottom:12px}
.arrow span{color:${t["pink-text"]};font-size:12px;font-weight:600;line-height:1.3;display:block}
.arrow::after{content:"";position:absolute;left:8px;right:8px;bottom:4px;height:2px;background:${t.pink}}
.arrow::before{content:"";position:absolute;right:6px;bottom:0;border:5px solid transparent;border-left:8px solid ${t.pink};border-right:0}
.m .flow{flex-direction:column;align-items:stretch}
.m .arrow{width:auto;padding:4px 0 4px 34px;text-align:left}
.m .arrow::after{left:20px;right:auto;top:0;bottom:0;width:2px;height:auto}
.m .arrow::before{left:15px;right:auto;bottom:-4px;border:6px solid transparent;border-top:8px solid ${t.pink};border-bottom:0}
.half{display:flex;flex-direction:column;gap:6px}
.half ul{display:flex;flex-direction:column;gap:3px;color:${t.body};font-size:14px}
/* A/B */
.now{display:flex;flex-wrap:wrap;align-items:baseline;gap:6px 14px}
.eq{color:${t.body};font-size:14px}
.res{font-size:22px;color:${t.ink}}
.now .res{margin-left:auto;font-size:18px}
.option{display:flex;flex-direction:column;gap:4px}
/* checklist */
.checks{display:flex;flex-direction:column;gap:7px;margin-top:4px}
.checks li{display:flex;gap:8px;align-items:flex-start;color:${t.body};font-size:14px}
.check{flex:none;display:inline-flex;align-items:center;justify-content:center;width:20px;height:20px;margin-top:1px;border:1.5px solid ${t.ink};border-radius:6px;background:${t.bg};color:${t.ink};font-size:11px;font-weight:600}
.m .checklist .col{display:flex;align-items:stretch}
.m .only-d,.d .only-m{display:none}
/* periods */
.periods{display:flex;flex-direction:column;gap:10px}
.period{display:grid;grid-template-columns:80px 1fr;align-items:center;gap:10px}
.m .period{grid-template-columns:1fr;gap:4px}
.days{display:flex;align-items:center;gap:6px}
.m .days{gap:4px}
.day{width:52px;padding:8px 0;text-align:center;border:1px solid ${t.hairline};border-radius:8px;background:${t.bg};font-size:13px;font-weight:500}
.m .day{width:34px;padding:7px 0;font-size:12px}
.day--sale{background:${t["pink-tint"]};border-color:${t.pink};color:${t["pink-text"]};font-weight:600}
.day--today{width:auto;padding:8px 10px;margin-left:8px;border-style:dashed;border-color:${t.muted};background:repeating-linear-gradient(135deg,${t.bg} 0 5px,${t.hairline} 5px 7px);color:${t.muted};white-space:nowrap}
.m .day--today{width:auto;padding:7px 6px;margin-left:4px}
.legend{display:flex;flex-wrap:wrap;gap:6px 18px;color:${t.body};font-size:13px}
.sw{display:inline-block;width:14px;height:14px;margin-right:6px;border-radius:4px;vertical-align:-2px;border:1px solid transparent}
.sw--sale{background:${t["pink-tint"]};border-color:${t.pink}}
.sw--today{border:1px dashed ${t.muted};background:repeating-linear-gradient(135deg,${t.bg} 0 3px,${t.hairline} 3px 5px)}
.sw--neg{background:${t["pink-text"]}}
.sw--pos{background:${t["cat-optimize-accent"]}}
.rules{display:grid;grid-template-columns:1fr 1fr;gap:8px 16px}
.m .rules{grid-template-columns:1fr}
.rules li{display:flex;gap:8px;align-items:center;color:${t.ink};font-weight:500;font-size:14px}
.rules .check{background:${t.ink};color:${t.bg}}
/* bars */
.bars{display:flex;flex-direction:column;gap:8px}
.brow{display:grid;grid-template-columns:120px 1fr 170px;align-items:center;gap:12px}
.m .brow{grid-template-columns:1fr auto;row-gap:4px}
.m .blabel{grid-column:1;grid-row:1}
.m .bval{grid-column:2;grid-row:1}
.m .track{grid-column:1/-1}
.blabel{font-weight:500}
.track{position:relative;height:22px}
.zero{position:absolute;left:50%;top:-4px;bottom:-4px;width:1px;background:${t.muted}}
.bar{position:absolute;top:3px;height:16px}
.bar--neg{background:${t["pink-text"]};border-radius:4px 0 0 4px}
.bar--pos{background:${t["cat-optimize-accent"]};border-radius:0 4px 4px 0}
.bar--ink{background:${t.ink};border-radius:4px 0 0 4px}
.bval{font-weight:600;font-variant-numeric:tabular-nums;text-align:right}
.bval em{display:block;font-style:normal;font-weight:500;font-size:12px;color:${t["pink-text"]}}
.brow--total{padding-top:10px;border-top:1px solid ${t.hairline}}
/* P39-D */
.center{text-align:center}
.sect{display:flex;flex-direction:column;gap:10px}
.sect-head{display:flex;align-items:center;gap:10px}
.statuses{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px}
.m .statuses{grid-template-columns:1fr 1fr}
.status{display:flex;flex-direction:column;gap:2px;padding:10px 12px;border:1px dashed ${t["chrome-dot"]};border-radius:10px;background:${t.alt}}
.status strong{color:${t.body}}
.status--ok{border:1px solid ${t.pink};box-shadow:0 0 0 1px ${t.pink} inset;background:${t["pink-tint"]}}
.status--ok strong{color:${t.ink}}
.verdict{font-size:12px;font-weight:600;color:${t.muted}}
.status--ok .verdict{color:${t["pink-text"]}}
.path{display:grid;grid-template-columns:1fr auto 1fr auto 1fr auto 1fr;align-items:stretch;gap:6px}
.d .crumb{display:flex;align-items:center;justify-content:center;text-align:center}
.d .sep{align-self:center}
.m .path{display:flex;flex-direction:column;align-items:stretch;gap:2px}
.crumb{padding:7px 12px;border:1px solid ${t.hairline};border-radius:10px;background:${t.bg};font-weight:500;font-size:14px}
.crumb--ink{background:${t.ink};border-color:${t.ink};color:${t.bg}}
.sep{color:${t["pink-text"]};font-weight:600}
.m .sep{transform:rotate(90deg);align-self:flex-start;margin-left:18px;line-height:1}
.desc{color:${t.body};font-size:14px}
.m .cards .col{display:flex}
ul.hang li{padding-left:14px;text-indent:-14px}
.half .metric{color:${t["pink-text"]}}
.vs .box{display:flex;flex-direction:column;gap:2px;background:${t.backdrop}}
.m .vs{grid-template-columns:1fr 1fr}
.look{margin-top:2px;color:${t.ink}!important}
.look b{font-weight:600}
/* P46-B1 */
.vv{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:4px 14px;border-style:dashed;border-color:${t.muted};background:${t.alt}}
.vv div{display:flex;align-items:baseline;gap:10px}
.vv-num{font-size:18px}
.op--accent{padding:2px 10px;border-radius:999px;background:${t["pink-tint"]};border:1px solid ${t.pink}}
.half .sect-head{gap:8px}
.cards .metric{font-size:14px}
.m .paths .col{align-items:flex-start}
/* P46-C2 */
.costs{display:flex;flex-direction:column;gap:6px;margin-top:4px}
.costs li{display:flex;justify-content:space-between;gap:10px;color:${t.body};font-size:14px}
.costs li::before{display:none!important}
.costs b{font-weight:600;color:${t.ink};font-variant-numeric:tabular-nums;white-space:nowrap}
.costs-total{padding-top:6px;border-top:1px solid ${t.hairline}}
.costs-total span{color:${t.ink};font-weight:600}
.wf{display:flex;flex-direction:column;gap:8px}
.wrow{display:grid;grid-template-columns:220px 1fr 110px;align-items:center;gap:12px}
.m .wrow{grid-template-columns:1fr auto;row-gap:4px}
.m .wrow .blabel{grid-column:1;grid-row:1}
.m .wrow .bval{grid-column:2;grid-row:1}
.m .wrow .wtrack{grid-column:1/-1}
.wtrack{position:relative;height:20px;background:${t.bg};border-radius:4px}
.wbar{position:absolute;top:2px;height:16px;border-radius:3px;min-width:4px}
.wbar--ink{background:${t.ink}}
.wbar--neg{background:${t["pink-text"]}}
.wbar--acc{background:${t.pink}}
.wrow--total{padding-top:8px;border-top:1px solid ${t.hairline}}
/* P46-C1 */
.bar--full{border-radius:4px}
.ledger{display:flex;flex-direction:column;gap:0;padding:4px 14px}
.lrow{display:flex;justify-content:space-between;gap:12px;padding:9px 0;border-bottom:1px solid ${t.hairline}}
.lrow:last-child{border-bottom:0}
.lrow span{color:${t.body}}
.lrow strong{font-variant-numeric:tabular-nums;white-space:nowrap}
.lrow:last-child strong{color:${t["pink-text"]}}
/* P46-D1 */
.bar--acc{background:${t.pink};border-radius:4px}
.tt{display:flex;flex-direction:column;padding:2px 14px}
.tt-row{display:grid;grid-template-columns:1.1fr 1fr 1fr;gap:12px;padding:9px 0;border-bottom:1px solid ${t.hairline};align-items:start}
.tt-row:last-child{border-bottom:0}
.tt-head span{color:${t.muted};font-size:13px;font-weight:600}
.tt-part{display:flex;flex-direction:column;gap:1px}
.tt-part em{font-style:normal;color:${t.muted};font-size:13px}
.tt-cell{color:${t.body};font-size:14px}
.tt-cell i{font-style:normal;color:${t.muted};font-size:13px;font-weight:600}
.m .tt-row{grid-template-columns:1fr;gap:3px}
.m .tt-head{display:none}
.tt-title{font-size:15px;line-height:1.4}
.tt-flags{display:flex;flex-direction:column;gap:5px;margin-top:2px}
.tt-flags li{display:flex;flex-direction:column;gap:0;font-size:14px;color:${t.body}}
.half ul.tt-flags li::before{display:none}
.tt-flags b{font-weight:600;color:${t["pink-text"]}}
.pc-wrap{display:grid;grid-template-columns:300px 1fr;gap:20px;align-items:start}
.m .pc-wrap{grid-template-columns:1fr;gap:14px}
.pcards{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.m .pcard:nth-child(n+3){display:none}
.pcard{display:flex;flex-direction:column;gap:6px;padding:8px;border:1px solid ${t.hairline};border-radius:12px;background:${t.bg}}
.pcard--accent{border-color:${t.pink};box-shadow:0 0 0 1px ${t.pink} inset}
.pc-img{position:relative;aspect-ratio:1;border-radius:8px;background:${t.backdrop}}
.pcard--accent .pc-img{background:${t["pink-tint"]};border:1.5px solid ${t.pink}}
.pc-line{position:relative;height:9px;border-radius:4px;background:${t["chrome-dot"]}}
.pc-price{position:relative;width:42%;height:11px;border-radius:4px;background:${t.ink}}
.pcard .num{position:absolute;width:22px;height:22px;font-size:12px}
.pc-img .num{top:8px;left:8px}
.pc-line .num,.pc-price .num{top:50%;right:-6px;transform:translateY(-50%)}
.pc-legend{display:flex;flex-direction:column;gap:12px}
.shot{position:relative;aspect-ratio:1;display:flex;align-items:flex-end;justify-content:center;gap:6%;padding-bottom:8%;border:1px solid ${t.hairline};border-radius:10px;background:#fff;overflow:hidden}
.m .cards .col .shot{width:120px}
.m .cards .col{display:flex;flex-direction:column}
.btl{position:relative;border:2px solid ${t.ink};border-radius:8px 8px 5px 5px;background:${t["pink-tint"]}}
.btl-cap{position:absolute;left:28%;right:28%;top:-14%;height:12%;border:2px solid ${t.ink};border-bottom:0;border-radius:4px 4px 0 0;background:${t.ink}}
.banner{position:absolute;left:0;right:0;top:46%;padding:6px 0;text-align:center;background:${t["pink-text"]};color:${t.bg};font-weight:600;font-size:15px}
/* P46-E */
.tl{display:grid;grid-template-columns:2fr 1fr 1fr;gap:6px}
.tl>div{display:flex;flex-direction:column;gap:2px;grid-column:var(--c)}
.tl span{color:${t.body};font-size:13px}
.seg{grid-row:1;padding:10px 12px;border:1px solid ${t.hairline};border-radius:10px;background:${t.bg}}
.seg--base{background:${t.backdrop}}
.mark{grid-row:2;padding:2px 10px 2px 0;border-right:3px solid ${t.pink};text-align:right}
.mark strong{color:${t["pink-text"]}}
.mark--ink{border-right-color:${t.ink}}
.mark--ink strong{color:${t.ink}}
.m .tl{display:flex;flex-direction:column}
.m .mark{padding:2px 0 2px 10px;border-right:0;border-left:3px solid ${t.pink};text-align:left}
.m .mark--ink{border-left-color:${t.ink}}
.dchart{display:flex;align-items:stretch;gap:8px;height:150px;padding-top:20px}
.m .dchart{height:130px;gap:6px}
.dgroup{position:relative;flex:1;display:flex;align-items:flex-end;gap:3px;border-bottom:1px solid ${t.muted}}
.m .dgroup{gap:2px}
.dbar{flex:1;display:block;border-radius:3px 3px 0 0}
.dbar--base{background:${t["chrome-dot"]}}
.dbar--after{background:${t.pink}}
.dbar--sale{background:${t["pink-text"]}}
.dbar--mark{outline:2px solid ${t.ink};outline-offset:1px}
.avg{position:absolute;left:0;right:0;border-top:2px dashed ${t.ink}}
.avg--ref{border-top-color:${t.muted}}
.dsplit{flex:none;width:2px;background:${t.ink};position:relative}
.dsplit span{position:absolute;top:-20px;left:50%;transform:translateX(-50%);white-space:nowrap;font-size:12px;font-weight:600;color:${t.ink}}
.dlabels{display:grid;grid-template-columns:1fr 1fr;gap:12px;color:${t.body};font-size:13px;font-weight:500}
.dlabels span:last-child{text-align:right}
.m .dlabels{gap:8px;font-size:12px}
.wins{display:flex;flex-direction:column;gap:12px}
.win{display:grid;grid-template-columns:200px 1fr;grid-template-areas:"t c" "t v";column-gap:14px;row-gap:4px;align-items:center}
.win strong{grid-area:t;font-size:14px}
.win .cells{grid-area:c}
.win .verdict{grid-area:v;font-size:13px}
.m .win{grid-template-columns:1fr;grid-template-areas:"t" "c" "v"}
.win--ok .verdict{color:${t["pink-text"]}}
.cells{display:flex;gap:2px}
.cell{flex:1;display:block;height:22px;border-radius:3px;border:1px solid transparent}
.m .cell{height:18px;border-radius:2px}
.cell--base{background:${t.backdrop};border-color:${t.hairline}}
.cell--after{background:${t.bg};border-color:${t.hairline}}
.cell--sale{background:${t["pink-tint"]};border-color:${t.pink}}
.cell--start{margin-left:6px;position:relative}
.cell--start::before{content:"";position:absolute;left:-6px;top:-4px;bottom:-4px;width:2px;background:${t.ink}}
.sw--base{background:${t.backdrop};border-color:${t.hairline}}
.sw--after{background:${t.bg};border-color:${t.hairline}}
.pchart{display:grid;grid-template-columns:14fr 13fr 14fr;gap:8px;height:160px}
.m .pchart{height:120px;gap:5px}
.pgroup{position:relative;display:flex;align-items:flex-end;gap:2px;border-bottom:1px solid ${t.muted}}
.m .pgroup{gap:1px}
.pgroup--sale{background:${t["pink-tint"]};border-radius:6px 6px 0 0}
.phases{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px}
.m .phases{grid-template-columns:1fr 1fr}
.phase{display:flex;flex-direction:column;gap:2px;padding:10px 12px}
.grid4{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}
.m .grid4{grid-template-columns:1fr}
.ttable{display:flex;flex-direction:column;gap:6px}
.trow{display:grid;grid-template-columns:140px repeat(4,minmax(0,1fr));gap:8px;align-items:center;padding:8px 12px;border:1px solid ${t.hairline};border-radius:10px;background:${t.bg};font-variant-numeric:tabular-nums}
.trow span{text-align:right;font-weight:600}
.trow .tlabel{text-align:left;font-weight:500}
.trow em{display:none;font-style:normal}
.trow--head{border:0;background:none;padding-top:0;padding-bottom:0}
.trow--head span{color:${t.muted};font-size:13px;font-weight:600}
.trow--accent{border-color:${t.pink};box-shadow:0 0 0 1px ${t.pink} inset;background:${t["pink-tint"]}}
.trow--accent .tpct{color:${t["pink-text"]}}
.trow--total{background:${t.ink};border-color:${t.ink};color:${t.bg}}
.m .trow{grid-template-columns:repeat(4,minmax(0,1fr));row-gap:4px;padding:8px 10px}
.m .trow .tlabel{grid-column:1/-1}
.m .trow span{text-align:left;display:flex;flex-direction:column;font-size:14px}
.m .trow em{display:block;color:${t.muted};font-size:11px;font-weight:500}
.m .trow--total em{color:${t["chrome-dot"]}}
.m .trow--head{display:none}
</style></head><body class="${layout === "mobile" ? "m" : "d"}"><div class="fig">${diagram.html(t)}</div></body></html>`;
}

/** Renders one layout; returns its CSS height (even, so the half-width variant has no rounding tie). */
async function render(browser, html, layout, file) {
  const { width, scale } = LAYOUTS[layout];
  const page = await browser.newPage({ viewport: { width, height: 200 }, deviceScaleFactor: scale });
  await page.setContent(html);
  await page.evaluate(() => document.fonts.ready);
  const measured = await page.evaluate(() => document.querySelector(".fig").getBoundingClientRect().height);
  let height = Math.ceil(measured);
  if (height % 2 === 1) height += 1;
  await page.setViewportSize({ width, height });
  await page.screenshot({ path: file, type: "png" });
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
  await page.close();
  if (overflow) throw new Error(`${file}: content wider than the ${width}px layout`);
  return height;
}

function outputs(name, layout) {
  const { widths, suffix } = LAYOUTS[layout];
  const stem = join(MEDIA, `blog-fig-${name.replace(/-v(\d+)$/, `${suffix}-v$1`)}`);
  return { stem, files: widths.flatMap((w) => [`${stem}-${w}.avif`, `${stem}-${w}.webp`]) };
}

async function main() {
  const args = process.argv.slice(2);
  const samplesAt = args.indexOf("--samples");
  const tokens = readTokens();
  const browser = await chromium.launch();
  try {
    const tmp = samplesAt !== -1 ? resolve(args[samplesAt + 1] ?? ".") : mkdtempSync(join(tmpdir(), "blog-diagrams-"));
    mkdirSync(tmp, { recursive: true });
    for (const diagram of DIAGRAMS) {
      const heights = {};
      for (const layout of Object.keys(LAYOUTS)) {
        const html = pageHtml(diagram, tokens, layout);
        if (samplesAt !== -1) {
          heights[layout] = await render(browser, html, layout, join(tmp, `${diagram.name}-${layout}.png`));
          continue;
        }
        const { stem, files } = outputs(diagram.name, layout);
        const existing = files.filter((f) => existsSync(f));
        if (existing.length === files.length) {
          heights[layout] = "exists";
          continue;
        }
        if (existing.length > 0) {
          throw new Error(`${diagram.name} (${layout}): partial output exists; remove it or bump -vN`);
        }
        const master = join(tmp, `${diagram.name}-${layout}.png`);
        heights[layout] = await render(browser, html, layout, master);
        execFileSync(
          PYTHON,
          [join(LANDING, "scripts", "media.py"), "optimize", master, "--out", stem, "--widths", LAYOUTS[layout].widths.join(",")],
          { stdio: "inherit" },
        );
      }
      console.log(`${diagram.name}: desktop height ${heights.desktop}, mobile height ${heights.mobile}`);
    }
  } finally {
    await browser.close();
  }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  await main();
}
