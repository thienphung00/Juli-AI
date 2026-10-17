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
    name: "checklist-khong-ra-don-v1",
    html: () => {
      const groups = [
        ["Sản phẩm có bán được không", ["Trạng thái Trực tuyến", "Biến thể chính còn hàng", "Giao đúng hạn, xử lý đơn nhanh"]],
        ["Phễu nghẽn ở bước nào", ["Lượt hiển thị đủ ngưỡng", "CTR so với chính nó và sản phẩm khác", "CTR chỉ giảm ở luồng vừa tăng traffic", "Tỷ lệ thêm vào giỏ hàng", "Đơn trên mỗi lượt thêm vào giỏ"]],
        ["Đo cho đúng", ["Đủ dữ liệu ở mỗi kỳ", "Một thay đổi, một ngày bắt đầu"]],
      ];
      let n = 0;
      return `${head(`Kiểm tra theo thứ tự, <span class="only-d">từ trái sang phải</span><span class="only-m">từ trên xuống</span>`)}
<div class="grid3 checklist">${groups
        .map(
          ([title, items]) =>
            `<div class="box col"><strong>${title}</strong><ul class="checks">${items
              .map((item) => `<li><span class="check">${++n}</span>${item}</li>`)
              .join("")}</ul></div>`,
        )
        .join("")}</div>`;
    },
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
    name: "doc-pheu-o-dau-v1",
    html: () => {
      const path = ["Trung tâm nhà bán hàng", "La bàn dữ liệu", "Số liệu phân tích sản phẩm", "Lưu lượng truy cập sản phẩm"];
      const rules = [
        ["Chọn luồng", "Đọc Thẻ sản phẩm trước: không có người dẫn LIVE hay nhà sáng tạo bán hộ."],
        ["Chọn khoảng thời gian", "Ít nhất 14 ngày, tốt hơn 28 hoặc 30 ngày. Cộng tổng cả kỳ rồi mới chia ra tỷ lệ."],
        ["Đủ dữ liệu chưa", "Juli đọc CTR từ 50 lượt hiển thị mỗi ngày, CTOR từ 20 lượt nhấp mỗi ngày."],
      ];
      return `${head("Phễu của từng sản phẩm nằm ở đâu")}
<div class="path">${path
        .map((p, i) => `<span class="crumb${i === path.length - 1 ? " crumb--ink" : ""}">${p}</span>`)
        .join(`<span class="sep">›</span>`)}</div>
<p class="label">Rồi đọc theo ba quy tắc</p>
<div class="grid3">${rules
        .map(([t, d], i) => `<div class="box col">${num(i + 1)}<strong>${t}</strong><span class="desc">${d}</span></div>`)
        .join("")}</div>
<p class="note">Ngưỡng ở mục 3 là quy tắc của Juli, không phải quy định của TikTok. Dưới ngưỡng, ghi “chưa đủ dữ liệu”: vấn đề thường nằm ở Lượt hiển thị.</p>`;
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
