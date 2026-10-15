import { breadcrumbSchema, buildMetadata, JsonLd } from "../../lib/seo";
import { COMPANY } from "../../lib/site";
import { LegalPage, LegalSection } from "../privacy/legal-template";

export const metadata = buildMetadata("/terms");

const LAST_UPDATED = "15/10/2026";

/**
 * "Tóm tắt dễ hiểu" (D44): each line restates a numbered section below
 * (§2 + §6, §5, §3 + §4, §8). It adds no term; the full text governs.
 */
const SUMMARY = [
  "Juli phân tích dữ liệu shop TikTok Shop và đề xuất việc nên làm; bạn là người quyết định, và Juli chỉ làm khi bạn đồng ý.",
  "Tài khoản mới dùng thử miễn phí 3 tháng, không cần thẻ thanh toán; sau đó phí dịch vụ là 500.000đ mỗi tháng.",
  "Bạn cần từ 18 tuổi trở lên, và là chủ shop hoặc được chủ shop uỷ quyền khi kết nối shop.",
  "Bạn có thể ngừng sử dụng Juli và yêu cầu xoá tài khoản bất kỳ lúc nào.",
] as const;

const TOC = [
  { id: "dieu-1", label: "1. Giới thiệu" },
  { id: "dieu-2", label: "2. Juli AI là gì" },
  { id: "dieu-3", label: "3. Tài khoản của bạn" },
  { id: "dieu-4", label: "4. Kết nối shop" },
  { id: "dieu-5", label: "5. Phí dịch vụ" },
  { id: "dieu-6", label: "6. Đề xuất của Juli" },
  { id: "dieu-7", label: "7. Sử dụng hợp lệ" },
  { id: "dieu-8", label: "8. Chấm dứt" },
  { id: "dieu-9", label: "9. Thay đổi điều khoản" },
  { id: "dieu-10", label: "10. Liên hệ" },
  { id: "lien-he-dieu-khoan", label: "Liên hệ về điều khoản" },
] as const;

export default function TermsOfServicePage() {
  return (
    <>
      <JsonLd data={breadcrumbSchema("/terms")} />
      <LegalPage
        contactId="lien-he-dieu-khoan"
        contactTitle="Liên hệ về điều khoản"
        effective={LAST_UPDATED}
        summary={SUMMARY}
        title="Điều khoản dịch vụ"
        toc={TOC}
        updated={LAST_UPDATED}
      >
          <LegalSection headingId="dieu-1" num="1." title="Giới thiệu">
            <p>
              Juli AI (&quot;Juli&quot;) là dịch vụ do {COMPANY.name} (mã số thuế{" "}
              {COMPANY.taxId}, trụ sở tại {COMPANY.address}) cung cấp. Bằng việc đăng nhập
              hoặc sử dụng Juli, bạn đồng ý với các điều khoản này và với{" "}
              <a href="/privacy">
                Chính sách bảo mật
              </a>
              . Nếu bạn sử dụng Juli thay mặt một doanh nghiệp, bạn xác nhận mình có quyền
              chấp nhận các điều khoản này thay cho doanh nghiệp đó.
            </p>
          </LegalSection>

          <LegalSection headingId="dieu-2" num="2." title="Juli AI là gì">
            <p>
              Juli AI là trợ lý giúp người bán TikTok Shop tăng trưởng và tối ưu vận hành:
              theo dõi shop, phân tích dữ liệu (đơn hàng, sản phẩm, tồn kho, đơn hoàn, hiệu
              suất theo từng luồng truy cập) và đề xuất hành động phù hợp. Bạn phê duyệt,
              Juli mới thực hiện — Juli không tự động thay đổi shop thật của bạn nếu chưa có
              sự đồng ý của bạn, và mỗi thao tác trên shop thật (ví dụ: tạo mã giảm giá) cần
              một quyền ghi riêng, có thời hạn, cho từng trường hợp.
            </p>
          </LegalSection>

          <LegalSection headingId="dieu-3" num="3." title="Tài khoản của bạn">
            <p>
              Bạn phải từ 18 tuổi trở lên để sử dụng Juli. Bạn tạo và truy cập tài khoản
              Juli bằng cách đăng nhập với Google. Bạn chịu trách nhiệm bảo mật tài khoản
              Google của mình; mọi hoạt động qua tài khoản Google đã đăng nhập được xem là
              hoạt động của bạn.
            </p>
          </LegalSection>

          <LegalSection headingId="dieu-4" num="4." title="Kết nối shop">
            <p>
              Khi bạn kết nối shop TikTok Shop, bạn cho phép Juli đọc dữ liệu shop của bạn
              (mục 4 của{" "}
              <a href="/privacy">
                Chính sách bảo mật
              </a>
              ) để tạo đề xuất. Bạn xác nhận mình là chủ shop hoặc được chủ shop uỷ quyền
              kết nối. Bạn có thể ngắt kết nối bất kỳ lúc nào; khi đó Juli ngừng đồng bộ dữ
              liệu mới và không thể tiếp tục đề xuất cho shop đó.
            </p>
            <p id="shopee">
              Shopee đang được tích hợp qua Shopee Open Platform; hiện Juli chưa đọc dữ liệu
              hay thay đổi gì trên shop Shopee. Khi tính năng này sẵn sàng và bạn kết nối
              shop Shopee, các điều khoản này áp dụng tương tự như với TikTok Shop, đồng
              thời điều khoản và chính sách của Shopee và Shopee Open Platform vẫn áp dụng.
              Dữ liệu Shopee được xử lý theo mục 4A của{" "}
              <a href="/privacy">
                Chính sách bảo mật
              </a>
              .
            </p>
            <p lang="en">
              <em>English:</em> Shopee is being integrated through Shopee Open Platform; Juli
              does not yet read data from, or change anything on, any Shopee shop. Once
              available and you connect a Shopee shop, these terms apply as they do to
              TikTok Shop, and Shopee&rsquo;s and Shopee Open Platform&rsquo;s own terms and
              policies also apply. Shopee data is handled as described in section 4A of the
              Privacy Policy.
            </p>
          </LegalSection>

          <LegalSection headingId="dieu-5" num="5." title="Phí dịch vụ">
            <p>
              Tài khoản mới được dùng thử miễn phí 3 tháng kể từ ngày đăng ký, không cần thẻ
              thanh toán. Sau thời gian dùng thử, phí dịch vụ Juli là 500.000đ/tháng. Bạn có
              thể huỷ bất cứ lúc nào. Phí đã thanh toán không thể hoàn lại.
            </p>
          </LegalSection>

          <LegalSection headingId="dieu-6" num="6." title="Đề xuất của Juli">
            <p>
              Các đề xuất của Juli được tạo bằng AI dựa trên dữ liệu shop và chỉ mang tính
              tương đối. Juli chỉ thực hiện một hành động khi bạn đồng ý, và bạn là người
              quyết định cuối cùng cho mọi hành động trên shop của mình.
            </p>
          </LegalSection>

          <LegalSection headingId="dieu-7" num="7." title="Sử dụng hợp lệ">
            <p>
              Bạn đồng ý không sử dụng Juli để vi phạm pháp luật hoặc chính sách của TikTok
              Shop hoặc Shopee, không truy cập trái phép vào hệ thống hay dữ liệu của người khác, và
              không sao chép, dịch ngược hoặc khai thác Juli ngoài mục đích vận hành shop
              của bạn.
            </p>
          </LegalSection>

          <LegalSection headingId="dieu-8" num="8." title="Chấm dứt">
            <p>
              Bạn có thể ngừng sử dụng Juli và yêu cầu xoá tài khoản bất kỳ lúc nào. Juli có
              thể tạm ngưng hoặc chấm dứt tài khoản vi phạm các điều khoản này hoặc chính
              sách của sàn. Nếu Juli ngừng cung cấp dịch vụ, chúng tôi sẽ thông báo cho bạn
              ít nhất 30 ngày trước.
            </p>
          </LegalSection>

          <LegalSection headingId="dieu-9" num="9." title="Thay đổi điều khoản">
            <p>
              Khi điều khoản thay đổi, chúng tôi cập nhật ngày ở đầu trang này. Với những
              thay đổi quan trọng, chúng tôi thông báo qua email ít nhất 7 ngày trước khi
              thay đổi có hiệu lực. Việc tiếp tục sử dụng Juli sau thời điểm đó đồng nghĩa
              với việc bạn chấp nhận điều khoản mới.
            </p>
          </LegalSection>

          <LegalSection headingId="dieu-10" num="10." title="Liên hệ">
            <p>
              Mọi câu hỏi về điều khoản này, vui lòng liên hệ {COMPANY.name} qua{" "}
              <a href={`mailto:${COMPANY.email}`}>
                {COMPANY.email}
              </a>
              .
            </p>
          </LegalSection>
      </LegalPage>
    </>
  );
}
