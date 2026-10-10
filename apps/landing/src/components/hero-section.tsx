import Link from "next/link";

import { DEMO_URL, LOGIN_URL } from "../lib/site";
import { CtaLink } from "./cta-link";

/** The outcome triplet, rendered one promise per line under the body copy. */
const PROMISES = [
  "Hướng đến +1–3% GMV mỗi tháng",
  "Tiết kiệm ~1,7 giờ/ngày mỗi nhân sự",
  "Mở rộng tinh gọn, ROI cao (chi phí từ 500K)",
] as const;

/**
 * The sales demo (juli-content-engine `sales-demo-01`, re-encoded to 720p).
 * `preload="none"` keeps the ~15MB file off the critical path until the
 * visitor presses play; the poster is the 5-traffic-source GMV table frame.
 */
const DEMO_VIDEO_SRC = "/videos/juli-demo.mp4";
const DEMO_VIDEO_POSTER = "/videos/juli-demo-poster.jpg";

export function HeroSection() {
  return (
    <section aria-labelledby="hero-heading" className="lp-hero">
      <div className="lp-hero__copy">
        <p className="lp-hero__badge">
          TikTok Shop Partner ✓
          <span className="lp-hero__badge-soon">Shopee · sắp ra mắt</span>
        </p>
        <p className="lp-hero__eyebrow">
          Chi phí vận hành và hoa hồng sàn ngày càng tăng?
        </p>
        <h1 className="lp-hero__heading" id="hero-heading">
          Tăng trưởng GMV ổn định và mở rộng mà không cần chi thêm nhiều ngân
          sách.
        </h1>
        <p className="lp-hero__body">
          Juli là trợ lý giúp bạn tăng trưởng ổn định và tối ưu vận hành TikTok
          Shop và Shopee. Juli giúp mang lại hiệu suất cho các Lượt hiển thị,
          tỷ lệ bấm, tỷ lệ đặt hàng, giá trị mỗi đơn từ đó:
        </p>
        <p className="lp-hero__promise">
          {PROMISES.map((promise) => (
            <span className="lp-hero__promise-line" key={promise}>
              {promise}
            </span>
          ))}
        </p>
        <div className="lp-hero__actions">
          <CtaLink data-testid="hero-demo-cta" href={DEMO_URL} size="large">
            Trải nghiệm Demo
          </CtaLink>
          <CtaLink
            data-testid="hero-login-cta"
            href={LOGIN_URL}
            size="large"
            variant="secondary"
          >
            Đăng nhập / Đăng ký
          </CtaLink>
        </div>
        <p className="lp-hero__reassurance">
          Miễn phí thử nghiệm 3 tháng · Dành cho điện thoại · Kết quả trực tiếp
        </p>
        <p className="lp-hero__consent" data-testid="hero-consent-note">
          Bằng việc đăng nhập, bạn đồng ý với{" "}
          <Link className="lp-hero__consent-link" href="/terms">
            Điều khoản dịch vụ
          </Link>{" "}
          và{" "}
          <Link className="lp-hero__consent-link" href="/privacy">
            Chính sách bảo mật
          </Link>{" "}
          của Juli.
        </p>
      </div>
      <div className="lp-hero__visual">
        <video
          aria-label="Video demo Juli phân tích GMV theo 5 luồng truy cập của một TikTok Shop"
          className="lp-hero__video"
          controls
          data-testid="hero-demo-video"
          playsInline
          poster={DEMO_VIDEO_POSTER}
          preload="none"
          src={DEMO_VIDEO_SRC}
        />
      </div>
    </section>
  );
}
