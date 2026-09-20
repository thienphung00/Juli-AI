import type { Metadata } from "next";

import { LandingHeader } from "../../components/landing-header";
import { OwnerPlaceholder } from "../../components/owner-placeholder";
import { SiteFooter } from "../../components/site-footer";

export const metadata: Metadata = {
  title: "Chính sách bảo mật — Juli AI",
  description:
    "Juli AI đọc gì từ shop TikTok Shop của bạn, những gì được ghi lại, và cách dữ liệu đó được sử dụng.",
};

const LAST_UPDATED = "20/09/2026";

export default function PrivacyPolicyPage() {
  return (
    <>
      <LandingHeader showSectionNav={false} />
      <main className="lp-main">
        <article className="lp-legal">
          <p className="lp-legal__eyebrow">Pháp lý</p>
          <h1 className="lp-legal__heading">Chính sách bảo mật</h1>
          <p className="lp-legal__updated">Cập nhật lần cuối: {LAST_UPDATED}</p>

          <p className="lp-legal__notice">
            Trang này mô tả những gì Juli AI hiện đọc và ghi, dựa trên hành vi thực tế của
            sản phẩm. Nội dung do đội ngũ Juli soạn thảo và cần chủ sở hữu sản phẩm cùng bộ
            phận pháp lý rà soát trước khi được xem là chính sách chính thức, và trước khi
            nộp cho màn hình xin quyền (consent screen) của Google.
          </p>

          <section className="lp-legal__section">
            <h2 className="lp-legal__section-heading">1. Chúng tôi là ai</h2>
            <OwnerPlaceholder>
              tên pháp nhân vận hành Juli AI, mã số đăng ký kinh doanh, và địa chỉ liên hệ
              đầy đủ
            </OwnerPlaceholder>
            <p>
              Bạn có thể liên hệ chúng tôi qua email{" "}
              <a className="lp-legal__contact-link" href="mailto:lienhe@app-juli.com">
                lienhe@app-juli.com
              </a>
              .
            </p>
          </section>

          <section className="lp-legal__section">
            <h2 className="lp-legal__section-heading">
              2. Thông tin khi bạn đăng nhập bằng Google
            </h2>
            <p>
              Đăng nhập với Google là cách duy nhất để tạo và truy cập tài khoản Juli (thông
              qua Supabase Auth). Khi bạn đăng nhập, chúng tôi nhận địa chỉ email đã xác
              thực từ Google. Chúng tôi không yêu cầu bạn tạo hoặc nhập mật khẩu, và không
              yêu cầu số điện thoại để đăng nhập.
            </p>
            <OwnerPlaceholder>
              xác nhận danh sách đầy đủ thông tin hồ sơ Google được yêu cầu khi cấu hình màn
              hình xin quyền của Google (ví dụ: tên hiển thị, ảnh đại diện), và liệu số Zalo
              hay số điện thoại có được hỏi thêm một lần trong luồng lên nhóm (onboarding)
              hay không
            </OwnerPlaceholder>
          </section>

          <section className="lp-legal__section">
            <h2 className="lp-legal__section-heading">
              3. Thông tin chúng tôi đọc từ shop TikTok Shop của bạn
            </h2>
            <p>
              Sau khi bạn kết nối shop TikTok Shop, Juli đồng bộ định kỳ các dữ liệu sau từ
              API của TikTok Shop, dùng để phân tích và đưa ra đề xuất cho shop của bạn:
            </p>
            <ul aria-label="Dữ liệu shop Juli đọc">
              <li>Đơn hàng và chi tiết từng đơn hàng (mã đơn, trạng thái, giá trị, thời gian thanh toán/giao hàng)</li>
              <li>Sản phẩm (tên, danh mục, giá bán, doanh thu, số lượng đã bán)</li>
              <li>Tồn kho theo từng sản phẩm/SKU và kho hàng</li>
              <li>Đơn hoàn/hủy (loại hoàn, lý do, số tiền hoàn)</li>
              <li>Số liệu hiệu suất shop do TikTok Shop cung cấp (doanh thu, lượt xem, và các chỉ số phân tích khác)</li>
            </ul>
            <p>
              Đây là những dữ liệu Juli chủ động đồng bộ theo lịch từ TikTok Shop để vận
              hành sản phẩm; Juli không đọc tin nhắn cá nhân của bạn, và không lưu thông tin
              liên hệ của người mua ngoài mã định danh cần thiết để xử lý đơn hàng.
            </p>
          </section>

          <section className="lp-legal__section">
            <h2 className="lp-legal__section-heading">
              4. Những gì Juli ghi lại hoặc thay đổi trên shop của bạn
            </h2>
            <p>
              Mặc định, Juli không thay đổi bất kỳ điều gì trên shop TikTok Shop thật của
              bạn. Việc thử nghiệm các hành động (ví dụ: tạo mã giảm giá sản phẩm) hiện chỉ
              chạy trên môi trường thử nghiệm (sandbox) do TikTok cung cấp, tách biệt khỏi
              shop thật.
            </p>
            <p>
              Một đường ghi trên shop thật tồn tại trong sản phẩm nhưng mặc định đang tắt:
              nó chỉ chạy khi (a) bạn đã chủ động phê duyệt đề xuất, và (b) một quản trị viên
              của Juli đã cấp quyền riêng cho đúng một sản phẩm và đúng một loại thao tác,
              có thời hạn và chỉ dùng được một lần.
            </p>
            <OwnerPlaceholder>
              xác nhận lại trạng thái triển khai và phạm vi của đường ghi trên shop thật
              tại thời điểm công bố trang này, để nội dung không bị lạc hậu so với sản phẩm
            </OwnerPlaceholder>
          </section>

          <section className="lp-legal__section">
            <h2 className="lp-legal__section-heading">5. Thời gian lưu trữ dữ liệu</h2>
            <OwnerPlaceholder>
              thời gian lưu trữ dữ liệu shop và dữ liệu tài khoản, và điều gì xảy ra với dữ
              liệu khi bạn ngắt kết nối shop hoặc xoá tài khoản
            </OwnerPlaceholder>
          </section>

          <section className="lp-legal__section">
            <h2 className="lp-legal__section-heading">6. Chúng tôi chia sẻ dữ liệu với ai</h2>
            <p>Juli sử dụng các bên xử lý dữ liệu sau để vận hành sản phẩm:</p>
            <ul>
              <li>Supabase — xác thực đăng nhập (Google) và lưu trữ cơ sở dữ liệu</li>
              <li>TikTok Shop API — nguồn dữ liệu shop của bạn</li>
            </ul>
            <OwnerPlaceholder>
              xác nhận danh sách đầy đủ các bên xử lý dữ liệu (bao gồm nhà cung cấp hạ tầng
              máy chủ), và liệu có bên thứ ba nào khác nhận dữ liệu người bán hay không. Nếu
              Juli không bán dữ liệu người dùng cho bên thứ ba, xác nhận câu này trước khi
              công bố
            </OwnerPlaceholder>
          </section>

          <section className="lp-legal__section">
            <h2 className="lp-legal__section-heading">7. Quyền của bạn</h2>
            <OwnerPlaceholder>
              mô tả quyền truy cập, chỉnh sửa, xuất, và xoá dữ liệu của bạn, cách thực hiện
              các quyền đó, và khung pháp lý áp dụng (ví dụ: quy định bảo vệ dữ liệu cá nhân
              tại Việt Nam)
            </OwnerPlaceholder>
          </section>

          <section className="lp-legal__section">
            <h2 className="lp-legal__section-heading">8. Trẻ em</h2>
            <OwnerPlaceholder>tuyên bố về độ tuổi sử dụng dịch vụ</OwnerPlaceholder>
          </section>

          <section className="lp-legal__section">
            <h2 className="lp-legal__section-heading">9. Thay đổi chính sách này</h2>
            <OwnerPlaceholder>
              quy trình thông báo cho người dùng khi chính sách này thay đổi
            </OwnerPlaceholder>
          </section>

          <section className="lp-legal__section">
            <h2 className="lp-legal__section-heading">10. Liên hệ</h2>
            <p>
              Mọi câu hỏi về chính sách này, vui lòng liên hệ{" "}
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
