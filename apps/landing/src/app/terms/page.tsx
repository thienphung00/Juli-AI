import type { Metadata } from "next";

import { LandingHeader } from "../../components/landing-header";
import { OwnerPlaceholder } from "../../components/owner-placeholder";
import { SiteFooter } from "../../components/site-footer";

export const metadata: Metadata = {
  title: "Điều khoản dịch vụ — Juli AI",
  description: "Điều khoản sử dụng Juli AI, trợ lý AI cho người bán TikTok Shop.",
};

const LAST_UPDATED = "20/09/2026";

export default function TermsOfServicePage() {
  return (
    <>
      <LandingHeader showSectionNav={false} />
      <main className="lp-main">
        <article className="lp-legal">
          <p className="lp-legal__eyebrow">Pháp lý</p>
          <h1 className="lp-legal__heading">Điều khoản dịch vụ</h1>
          <p className="lp-legal__updated">Cập nhật lần cuối: {LAST_UPDATED}</p>

          <p className="lp-legal__notice">
            Trang này mô tả những gì Juli AI hiện làm, dựa trên hành vi thực tế của sản
            phẩm. Các điều khoản pháp lý (giới hạn trách nhiệm, bảo đảm, chấm dứt, luật áp
            dụng) cần chủ sở hữu sản phẩm và bộ phận pháp lý soạn thảo trước khi được xem là
            điều khoản chính thức, và trước khi nộp cho màn hình xin quyền (consent screen)
            của Google.
          </p>

          <section className="lp-legal__section">
            <h2 className="lp-legal__section-heading">1. Giới thiệu</h2>
            <OwnerPlaceholder>
              câu giới thiệu pháp lý chính thức — bên cung cấp dịch vụ, và việc sử dụng Juli
              đồng nghĩa với chấp nhận các điều khoản này
            </OwnerPlaceholder>
          </section>

          <section className="lp-legal__section">
            <h2 className="lp-legal__section-heading">2. Juli AI là gì</h2>
            <p>
              Juli AI là trợ lý giúp người bán TikTok Shop theo dõi shop, phân tích dữ liệu
              (đơn hàng, sản phẩm, tồn kho, đơn hoàn, hiệu suất) và đề xuất hành động phù
              hợp. Bạn phê duyệt, Juli mới thực hiện — Juli không tự động thay đổi shop thật
              của bạn nếu chưa có sự đồng ý của bạn, và các thao tác trên shop thật (ví dụ:
              tạo mã giảm giá) còn cần một quyền ghi riêng, có thời hạn, do quản trị viên
              Juli cấp cho từng trường hợp.
            </p>
          </section>

          <section className="lp-legal__section">
            <h2 className="lp-legal__section-heading">3. Tài khoản của bạn</h2>
            <p>
              Bạn tạo và truy cập tài khoản Juli bằng cách đăng nhập với Google. Bạn chịu
              trách nhiệm bảo mật tài khoản Google của mình; mọi hoạt động qua tài khoản
              Google đã đăng nhập được xem là hoạt động của bạn.
            </p>
          </section>

          <section className="lp-legal__section">
            <h2 className="lp-legal__section-heading">4. Kết nối shop TikTok Shop</h2>
            <p>
              Khi bạn kết nối shop TikTok Shop, bạn cho phép Juli đọc dữ liệu shop của bạn
              (mục 3 của{" "}
              <a className="lp-legal__contact-link" href="/privacy">
                Chính sách bảo mật
              </a>
              ) để tạo đề xuất. Bạn có thể ngắt kết nối bất kỳ lúc nào.
            </p>
            <OwnerPlaceholder>
              điều khoản về phạm vi uỷ quyền, trách nhiệm của người bán khi kết nối shop, và
              hậu quả khi ngắt kết nối
            </OwnerPlaceholder>
          </section>

          <section className="lp-legal__section">
            <h2 className="lp-legal__section-heading">5. Giới hạn trách nhiệm</h2>
            <OwnerPlaceholder>
              điều khoản giới hạn trách nhiệm — cần tư vấn pháp lý trước khi soạn thảo
            </OwnerPlaceholder>
          </section>

          <section className="lp-legal__section">
            <h2 className="lp-legal__section-heading">6. Bảo đảm</h2>
            <OwnerPlaceholder>
              tuyên bố miễn trừ bảo đảm — cần tư vấn pháp lý trước khi soạn thảo
            </OwnerPlaceholder>
          </section>

          <section className="lp-legal__section">
            <h2 className="lp-legal__section-heading">7. Chấm dứt</h2>
            <OwnerPlaceholder>
              điều kiện chấm dứt dịch vụ hoặc tài khoản, bởi bạn hoặc bởi Juli
            </OwnerPlaceholder>
          </section>

          <section className="lp-legal__section">
            <h2 className="lp-legal__section-heading">8. Luật áp dụng và giải quyết tranh chấp</h2>
            <OwnerPlaceholder>luật áp dụng và thẩm quyền giải quyết tranh chấp</OwnerPlaceholder>
          </section>

          <section className="lp-legal__section">
            <h2 className="lp-legal__section-heading">9. Thay đổi điều khoản</h2>
            <OwnerPlaceholder>
              quy trình thông báo cho người dùng khi điều khoản này thay đổi
            </OwnerPlaceholder>
          </section>

          <section className="lp-legal__section">
            <h2 className="lp-legal__section-heading">10. Liên hệ</h2>
            <p>
              Mọi câu hỏi về điều khoản này, vui lòng liên hệ{" "}
              <a className="lp-legal__contact-link" href="mailto:lienhe@app-juli.com">
                lienhe@app-juli.com
              </a>
              .
            </p>
          </section>
        </article>
      </main>
      <SiteFooter />
    </>
  );
}
