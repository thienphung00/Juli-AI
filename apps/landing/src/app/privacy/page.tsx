import type { Metadata } from "next";

import { LandingHeader } from "../../components/landing-header";
import { SiteFooter } from "../../components/site-footer";
import { COMPANY } from "../../lib/site";

export const metadata: Metadata = {
  title: "Chính sách bảo mật — Juli AI",
  description:
    "Juli AI thu thập gì, đọc gì từ shop TikTok Shop của bạn, chia sẻ với ai, lưu trong bao lâu, và quyền của bạn với dữ liệu đó.",
};

const LAST_UPDATED = "10/10/2026";

export default function PrivacyPolicyPage() {
  return (
    <>
      <LandingHeader showSectionNav={false} />
      <main className="lp-main">
        <article className="lp-legal">
          <p className="lp-legal__eyebrow">Pháp lý</p>
          <h1 className="lp-legal__heading">Chính sách bảo mật</h1>
          <p className="lp-legal__updated">Cập nhật lần cuối: {LAST_UPDATED}</p>

          <p className="lp-legal__intro">
            Chính sách này giải thích cách Juli AI thu thập, sử dụng, chia sẻ và bảo vệ dữ
            liệu khi bạn sử dụng website app-juli.com, bản Demo và ứng dụng Juli, phù hợp
            với Nghị định 13/2023/NĐ-CP về bảo vệ dữ liệu cá nhân.
          </p>

          <section className="lp-legal__section">
            <h2 className="lp-legal__section-heading">1. Chúng tôi là ai</h2>
            <p>
              Juli AI được vận hành bởi {COMPANY.name} (mã số thuế {COMPANY.taxId}), trụ sở
              tại {COMPANY.address}. {COMPANY.name} là bên kiểm soát và xử lý dữ liệu cá
              nhân được mô tả trong chính sách này.
            </p>
            <p>
              Bạn có thể liên hệ chúng tôi qua email{" "}
              <a className="lp-legal__contact-link" href={`mailto:${COMPANY.email}`}>
                {COMPANY.email}
              </a>
              .
            </p>
          </section>

          <section className="lp-legal__section">
            <h2 className="lp-legal__section-heading">2. Thông tin tài khoản</h2>
            <p>
              Đăng nhập với Google là cách duy nhất để tạo và truy cập tài khoản Juli (thông
              qua Supabase Auth). Chúng tôi không yêu cầu bạn tạo hoặc nhập mật khẩu.
            </p>
            <ul aria-label="Thông tin tài khoản Juli thu thập">
              <li>Từ Google: địa chỉ email đã xác thực, tên hiển thị và ảnh đại diện</li>
              <li>
                Tuỳ chọn: số Zalo hoặc mã người dùng Zalo, chỉ khi bạn bật nhận cảnh báo
                qua Zalo
              </li>
              <li>
                Tuỳ chọn: mã thiết bị, chỉ khi bạn bật thông báo đẩy trên điện thoại
              </li>
            </ul>
          </section>

          <section className="lp-legal__section">
            <h2 className="lp-legal__section-heading">
              3. Thông tin chúng tôi đọc từ shop của bạn
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
              <li>Số liệu hiệu suất shop do TikTok Shop cung cấp (doanh thu, lượt xem, tỷ lệ chuyển đổi theo từng luồng truy cập)</li>
              <li>Hiệu suất video và LIVE của shop, cùng các sản phẩm được gắn trong đó</li>
              <li>Chương trình khuyến mãi và mã giảm giá của shop</li>
            </ul>
            <p>
              Juli không đọc tin nhắn cá nhân của bạn, và không lưu thông tin liên hệ của
              người mua ngoài mã định danh cần thiết để xử lý đơn hàng. Hỗ trợ Shopee đang
              được phát triển; chính sách này sẽ được cập nhật trước khi Juli đọc dữ liệu
              từ Shopee.
            </p>
          </section>

          <section className="lp-legal__section">
            <h2 className="lp-legal__section-heading">
              4. Những gì Juli ghi lại hoặc thay đổi trên shop của bạn
            </h2>
            <p>
              Mặc định, Juli không thay đổi bất kỳ điều gì trên shop TikTok Shop thật của
              bạn. Việc thử nghiệm các hành động (ví dụ: tạo mã giảm giá sản phẩm) chạy trên
              môi trường thử nghiệm (sandbox) do TikTok cung cấp, tách biệt khỏi shop thật.
            </p>
            <p>
              Một thao tác trên shop thật chỉ được thực hiện khi (a) bạn đã chủ động phê
              duyệt đề xuất đó, và (b) quyền ghi được cấp riêng cho đúng một sản phẩm và
              đúng một loại thao tác, có thời hạn và chỉ dùng được một lần.
            </p>
          </section>

          <section className="lp-legal__section">
            <h2 className="lp-legal__section-heading">5. Mục đích sử dụng dữ liệu</h2>
            <ul>
              <li>Cung cấp, vận hành và bảo mật tài khoản và dịch vụ Juli</li>
              <li>Phân tích hiệu suất shop và tạo đề xuất tối ưu cho shop của bạn</li>
              <li>Gửi cảnh báo và thông báo mà bạn đã bật</li>
              <li>Đo lường hiệu quả quảng cáo của Juli trên TikTok</li>
              <li>Liên hệ hỗ trợ và thông báo các thay đổi quan trọng về dịch vụ</li>
            </ul>
          </section>

          <section className="lp-legal__section">
            <h2 className="lp-legal__section-heading">6. Chúng tôi chia sẻ dữ liệu với ai</h2>
            <p>
              Juli không bán dữ liệu của bạn cho bất kỳ bên thứ ba nào. Chúng tôi chỉ chia
              sẻ dữ liệu với các bên xử lý dữ liệu sau, trong phạm vi cần thiết để vận hành
              sản phẩm:
            </p>
            <ul aria-label="Bên xử lý dữ liệu">
              <li>Supabase — xác thực đăng nhập (Google) và lưu trữ cơ sở dữ liệu</li>
              <li>TikTok Shop API — nguồn dữ liệu shop của bạn</li>
              <li>
                OpenAI — mô hình AI phân tích dữ liệu shop và tạo đề xuất. Dữ liệu gửi qua
                API của OpenAI không được dùng để huấn luyện mô hình
              </li>
              <li>Nhà cung cấp máy chủ (VPS) — nơi chạy ứng dụng Juli</li>
              <li>Amazon Web Services (AWS) — quản lý khoá bí mật của hệ thống</li>
              <li>Zalo (Zalo OA) và Google Firebase — gửi cảnh báo và thông báo đẩy mà bạn đã bật</li>
              <li>
                TikTok Pixel và Events API — đo lường hiệu quả quảng cáo. Nhận địa chỉ
                IP, thông tin trình duyệt, trang bạn xem trên website này, và mã định
                danh quảng cáo của TikTok nếu bạn đến từ một quảng cáo. Nếu bạn đăng ký,
                email của bạn được băm (SHA-256) trước khi gửi — TikTok không nhận được
                email dạng gốc
              </li>
            </ul>
            <p>
              Một số bên xử lý trên đặt máy chủ ngoài Việt Nam (ví dụ: Hoa Kỳ), nên dữ liệu
              có thể được chuyển ra nước ngoài. Chúng tôi chỉ chuyển dữ liệu cần thiết cho
              mục đích nêu tại mục 5. Chúng tôi cũng có thể cung cấp dữ liệu khi cơ quan nhà
              nước có thẩm quyền yêu cầu theo quy định pháp luật.
            </p>
          </section>

          <section className="lp-legal__section">
            <h2 className="lp-legal__section-heading">7. Bảo mật và thời gian lưu trữ</h2>
            <p>
              Dữ liệu được mã hoá khi truyền (HTTPS). Quyền truy cập dữ liệu được giới hạn
              theo từng shop, và khoá truy cập TikTok Shop được lưu trong hệ thống quản lý
              khoá bí mật, không lưu trong mã nguồn.
            </p>
            <p>
              Chúng tôi lưu dữ liệu trong thời gian bạn sử dụng Juli. Khi bạn ngắt kết nối
              shop, Juli ngừng đồng bộ dữ liệu mới từ shop đó ngay lập tức. Khi bạn yêu cầu
              xoá tài khoản, dữ liệu tài khoản và dữ liệu shop được xoá trong vòng 30 ngày,
              trừ những dữ liệu pháp luật yêu cầu phải lưu giữ (ví dụ: chứng từ thanh toán).
            </p>
          </section>

          <section className="lp-legal__section">
            <h2 className="lp-legal__section-heading">8. Quyền của bạn</h2>
            <p>Theo Nghị định 13/2023/NĐ-CP, bạn có quyền:</p>
            <ul>
              <li>Được biết và truy cập dữ liệu cá nhân của mình</li>
              <li>Yêu cầu chỉnh sửa dữ liệu không chính xác</li>
              <li>Yêu cầu xuất bản sao dữ liệu của mình</li>
              <li>Yêu cầu xoá dữ liệu hoặc hạn chế xử lý dữ liệu</li>
              <li>Rút lại sự đồng ý bất kỳ lúc nào (ví dụ: ngắt kết nối shop, tắt cảnh báo)</li>
              <li>Khiếu nại về việc xử lý dữ liệu của mình</li>
            </ul>
            <p>
              Để thực hiện các quyền này, gửi yêu cầu tới{" "}
              <a className="lp-legal__contact-link" href={`mailto:${COMPANY.email}`}>
                {COMPANY.email}
              </a>
              . Chúng tôi phản hồi trong vòng 72 giờ.
            </p>
          </section>

          <section className="lp-legal__section">
            <h2 className="lp-legal__section-heading">9. Độ tuổi sử dụng</h2>
            <p>
              Juli là dịch vụ dành cho người bán hàng và doanh nghiệp. Bạn phải từ 18 tuổi
              trở lên để sử dụng Juli. Chúng tôi không cố ý thu thập dữ liệu của người dưới
              18 tuổi.
            </p>
          </section>

          <section className="lp-legal__section">
            <h2 className="lp-legal__section-heading">10. Thay đổi chính sách này</h2>
            <p>
              Khi chính sách thay đổi, chúng tôi cập nhật ngày ở đầu trang này. Với những
              thay đổi quan trọng, chúng tôi thông báo qua email ít nhất 7 ngày trước khi
              thay đổi có hiệu lực.
            </p>
          </section>

          <section className="lp-legal__section">
            <h2 className="lp-legal__section-heading">11. Liên hệ</h2>
            <p>
              Mọi câu hỏi về chính sách này, vui lòng liên hệ {COMPANY.name} qua{" "}
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
