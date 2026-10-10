import type { Metadata } from "next";

import { LandingHeader } from "../../components/landing-header";
import { SiteFooter } from "../../components/site-footer";
import { COMPANY } from "../../lib/site";

export const metadata: Metadata = {
  title: "Điều khoản dịch vụ — Juli AI",
  description:
    "Điều khoản sử dụng Juli AI, trợ lý tăng trưởng và tối ưu vận hành cho người bán TikTok Shop.",
};

const LAST_UPDATED = "10/10/2026";

export default function TermsOfServicePage() {
  return (
    <>
      <LandingHeader showSectionNav={false} />
      <main className="lp-main">
        <article className="lp-legal">
          <p className="lp-legal__eyebrow">Pháp lý</p>
          <h1 className="lp-legal__heading">Điều khoản dịch vụ</h1>
          <p className="lp-legal__updated">Cập nhật lần cuối: {LAST_UPDATED}</p>

          <section className="lp-legal__section">
            <h2 className="lp-legal__section-heading">1. Giới thiệu</h2>
            <p>
              Juli AI (&quot;Juli&quot;) là dịch vụ do {COMPANY.name} (mã số thuế{" "}
              {COMPANY.taxId}, trụ sở tại {COMPANY.address}) cung cấp. Bằng việc đăng nhập
              hoặc sử dụng Juli, bạn đồng ý với các điều khoản này và với{" "}
              <a className="lp-legal__contact-link" href="/privacy">
                Chính sách bảo mật
              </a>
              . Nếu bạn sử dụng Juli thay mặt một doanh nghiệp, bạn xác nhận mình có quyền
              chấp nhận các điều khoản này thay cho doanh nghiệp đó.
            </p>
          </section>

          <section className="lp-legal__section">
            <h2 className="lp-legal__section-heading">2. Juli AI là gì</h2>
            <p>
              Juli AI là trợ lý giúp người bán TikTok Shop tăng trưởng và tối ưu vận hành:
              theo dõi shop, phân tích dữ liệu (đơn hàng, sản phẩm, tồn kho, đơn hoàn, hiệu
              suất theo từng luồng truy cập) và đề xuất hành động phù hợp. Bạn phê duyệt,
              Juli mới thực hiện — Juli không tự động thay đổi shop thật của bạn nếu chưa có
              sự đồng ý của bạn, và mỗi thao tác trên shop thật (ví dụ: tạo mã giảm giá) cần
              một quyền ghi riêng, có thời hạn, cho từng trường hợp.
            </p>
          </section>

          <section className="lp-legal__section">
            <h2 className="lp-legal__section-heading">3. Tài khoản của bạn</h2>
            <p>
              Bạn phải từ 18 tuổi trở lên để sử dụng Juli. Bạn tạo và truy cập tài khoản
              Juli bằng cách đăng nhập với Google. Bạn chịu trách nhiệm bảo mật tài khoản
              Google của mình; mọi hoạt động qua tài khoản Google đã đăng nhập được xem là
              hoạt động của bạn.
            </p>
          </section>

          <section className="lp-legal__section">
            <h2 className="lp-legal__section-heading">4. Kết nối shop</h2>
            <p>
              Khi bạn kết nối shop TikTok Shop, bạn cho phép Juli đọc dữ liệu shop của bạn
              (mục 3 của{" "}
              <a className="lp-legal__contact-link" href="/privacy">
                Chính sách bảo mật
              </a>
              ) để tạo đề xuất. Bạn xác nhận mình là chủ shop hoặc được chủ shop uỷ quyền
              kết nối. Bạn có thể ngắt kết nối bất kỳ lúc nào; khi đó Juli ngừng đồng bộ dữ
              liệu mới và không thể tiếp tục đề xuất cho shop đó.
            </p>
          </section>

          <section className="lp-legal__section">
            <h2 className="lp-legal__section-heading">5. Phí dịch vụ</h2>
            <p>
              Phí dịch vụ Juli là 500.000đ/tháng. Bạn có thể huỷ bất cứ lúc nào. Phí đã
              thanh toán không thể hoàn lại.
            </p>
          </section>

          <section className="lp-legal__section">
            <h2 className="lp-legal__section-heading">6. Đề xuất của Juli</h2>
            <p>
              Các đề xuất của Juli được tạo bằng AI dựa trên dữ liệu shop và chỉ mang tính
              tương đối. Juli chỉ thực hiện một hành động khi bạn đồng ý, và bạn là người
              quyết định cuối cùng cho mọi hành động trên shop của mình.
            </p>
          </section>

          <section className="lp-legal__section">
            <h2 className="lp-legal__section-heading">7. Sử dụng hợp lệ</h2>
            <p>
              Bạn đồng ý không sử dụng Juli để vi phạm pháp luật hoặc chính sách của TikTok
              Shop, không truy cập trái phép vào hệ thống hay dữ liệu của người khác, và
              không sao chép, dịch ngược hoặc khai thác Juli ngoài mục đích vận hành shop
              của bạn.
            </p>
          </section>

          <section className="lp-legal__section">
            <h2 className="lp-legal__section-heading">8. Chấm dứt</h2>
            <p>
              Bạn có thể ngừng sử dụng Juli và yêu cầu xoá tài khoản bất kỳ lúc nào. Juli có
              thể tạm ngưng hoặc chấm dứt tài khoản vi phạm các điều khoản này hoặc chính
              sách của sàn. Nếu Juli ngừng cung cấp dịch vụ, chúng tôi sẽ thông báo cho bạn
              ít nhất 30 ngày trước.
            </p>
          </section>

          <section className="lp-legal__section">
            <h2 className="lp-legal__section-heading">9. Thay đổi điều khoản</h2>
            <p>
              Khi điều khoản thay đổi, chúng tôi cập nhật ngày ở đầu trang này. Với những
              thay đổi quan trọng, chúng tôi thông báo qua email ít nhất 7 ngày trước khi
              thay đổi có hiệu lực. Việc tiếp tục sử dụng Juli sau thời điểm đó đồng nghĩa
              với việc bạn chấp nhận điều khoản mới.
            </p>
          </section>

          <section className="lp-legal__section">
            <h2 className="lp-legal__section-heading">10. Liên hệ</h2>
            <p>
              Mọi câu hỏi về điều khoản này, vui lòng liên hệ {COMPANY.name} qua{" "}
              <a className="lp-legal__contact-link" href={`mailto:${COMPANY.email}`}>
                {COMPANY.email}
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
