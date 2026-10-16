import { breadcrumbSchema, buildMetadata, JsonLd } from "../../lib/seo";
import { COMPANY } from "../../lib/site";
import { LegalPage, LegalSection } from "../privacy/legal-template";

export const metadata = buildMetadata("/terms");

const VERSION = "2.2";
const LAST_UPDATED = "16/10/2026";

/**
 * "Tóm tắt dễ hiểu" (D44): each line restates a numbered section below
 * (§2 + §6, §5, §3 + §4, §8, §9). It adds no term; the full text governs.
 */
const SUMMARY = [
  "Juli phân tích dữ liệu shop TikTok Shop và đề xuất việc nên làm; bạn là người quyết định, và Juli chỉ làm khi bạn đồng ý.",
  "Tài khoản mới dùng thử miễn phí 3 tháng, không cần thẻ thanh toán; sau đó phí dịch vụ là 500.000đ mỗi tháng.",
  "Bạn cần từ 18 tuổi trở lên, và là chủ shop hoặc được chủ shop uỷ quyền khi kết nối shop.",
  "Dữ liệu shop thuộc về bạn; Juli chỉ xử lý dữ liệu đó để phục vụ shop của bạn và không bán dữ liệu.",
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
  { id: "dieu-8", label: "8. Dữ liệu của bạn" },
  { id: "dieu-9", label: "9. Chấm dứt" },
  { id: "dieu-10", label: "10. Thay đổi điều khoản" },
  { id: "dieu-11", label: "11. Liên hệ" },
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
        version={VERSION}
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
              Juli AI là trợ lý giúp người bán TMĐT tăng trưởng và tối ưu vận hành (hiện kết
              nối TikTok Shop, Shopee đang tích hợp): theo dõi shop, phân tích dữ liệu (đơn hàng, sản phẩm, tồn kho, đơn hoàn, hiệu
              suất theo từng luồng truy cập) và đề xuất hành động phù hợp. Bạn phê duyệt,
              Juli mới thực hiện — Juli không tự động thay đổi shop thật của bạn nếu chưa có
              sự đồng ý của bạn, và mỗi thao tác trên shop thật (ví dụ: tạo mã giảm giá) cần
              một quyền ghi riêng, có thời hạn, cho từng trường hợp.
            </p>
          </LegalSection>

          <LegalSection headingId="dieu-3" num="3." title="Tài khoản của bạn">
            <p>
              Bạn phải từ 18 tuổi trở lên để sử dụng Juli. Bạn tạo và truy cập tài khoản
              Juli bằng cách đăng nhập với Google hoặc bằng email với mã xác thực. Bạn chịu
              trách nhiệm bảo mật tài khoản Google và hộp thư email của mình; mọi hoạt động
              qua tài khoản đã đăng nhập được xem là hoạt động của bạn.
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

          <LegalSection headingId="dieu-8" num="8." title="Dữ liệu của bạn">
            <p>
              8.1. Dữ liệu shop và dữ liệu kinh doanh của bạn thuộc về bạn. Juli chỉ xử lý
              dữ liệu đó để cung cấp dịch vụ cho bạn, theo{" "}
              <a href="/privacy">
                Chính sách bảo mật
              </a>
              .
            </p>
            <p>
              8.2. Bạn bảo đảm mình có quyền cho phép Juli xử lý dữ liệu shop của bạn, bao
              gồm dữ liệu cá nhân của người mua có trong đó, và việc cho phép này phù hợp với
              chính sách của sàn (TikTok Shop, Shopee) và pháp luật về bảo vệ dữ liệu cá nhân.
            </p>
            <p>
              8.3. Với dữ liệu cá nhân của người mua có trong dữ liệu shop (ví dụ: mã định
              danh người mua trong đơn hàng), bạn là bên kiểm soát dữ liệu và Juli là bên xử
              lý dữ liệu thay mặt bạn. Juli cam kết:
            </p>
            <ul aria-label="Cam kết của Juli khi xử lý dữ liệu người mua">
              <li>(a) chỉ xử lý dữ liệu này theo mục đích cung cấp dịch vụ cho bạn;</li>
              <li>
                (b) áp dụng các biện pháp bảo vệ nêu tại Chính sách bảo mật và chỉ chia sẻ với
                các bên xử lý được liệt kê tại mục 7 của Chính sách bảo mật;
              </li>
              <li>
                (c) không bán, không tiết lộ và không chuyển giao dữ liệu này cho bất kỳ bên
                thứ ba nào ngoài các bên xử lý đó; không dùng dữ liệu để phục vụ khách hàng
                khác và không dùng để huấn luyện mô hình AI tổng quát;
              </li>
              <li>
                (d) chỉ truy cập và xử lý dữ liệu trong phạm vi quyền được cấp và cần thiết cho
                việc cung cấp dịch vụ, tuân thủ các chính sách về truy cập và bảo vệ dữ liệu
                của TikTok Shop và Shopee;
              </li>
              <li>
                (e) không gửi thông tin liên hệ hay mã định danh của người mua cho nhà cung cấp
                mô hình AI;
              </li>
              <li>
                (f) thông báo cho bạn chậm nhất 72 giờ sau khi phát hiện sự cố lộ, mất dữ liệu
                ảnh hưởng tới dữ liệu của bạn;
              </li>
              <li>(g) lưu trữ và xoá dữ liệu theo mục 8 của Chính sách bảo mật.</li>
            </ul>
            <p>
              8.4. Nội dung bạn tải lên hoặc nhập vào Juli (ví dụ: video, bản ghi LIVE, hình
              ảnh, Quy tắc của shop) có thể chứa giọng nói, hình ảnh của người khác (người
              dẫn LIVE, người mẫu), âm nhạc hoặc tác phẩm của bên thứ ba. Bạn bảo đảm mình có
              quyền sử dụng nội dung đó và đã có sự đồng ý cần thiết của những người xuất
              hiện trong đó để Juli xử lý cho mục đích phân tích. Juli chỉ dùng nội dung này
              để cung cấp dịch vụ cho bạn. Nếu Juli sử dụng nội dung đánh giá sản phẩm của
              người mua, Juli loại bỏ tên và thông tin định danh của người mua trước khi xử lý.
            </p>
            <p>
              8.5. Bạn không cung cấp cho Juli thông tin bạn không được phép chia sẻ, ví dụ
              thông tin mật của nhà cung cấp, đối tác hay của bên khác mà bạn có nghĩa vụ bảo
              mật. Dữ liệu thị trường và đối thủ Juli hiển thị cho bạn (ví dụ: giá bán, sản
              phẩm bán chạy, xu hướng ngành hàng) được Juli thu thập từ nguồn công khai hoặc
              từ nhà cung cấp dữ liệu thị trường bên thứ ba (ví dụ: FastMoss), chỉ mang tính
              tham khảo, và không lấy từ dữ liệu riêng của các shop khác dùng Juli.
            </p>
            <p>
              8.6. Cải thiện thuật toán: Juli được sử dụng dữ liệu shop đã được ẩn danh hoá,
              chỉ ở dạng cấu trúc dữ liệu (ví dụ: loại chỉ số, mối tương quan giữa các chỉ số,
              loại đề xuất và kết quả sau khi áp dụng) để tối ưu thuật toán phân tích và chất
              lượng gợi ý của Juli, bao gồm tinh chỉnh (fine-tune) mô hình ngôn ngữ của bên
              thứ ba thành mô hình riêng của Juli. Dữ liệu dùng cho mục đích này không chứa
              tên shop, tên hoặc nội dung sản phẩm, hình ảnh, kịch bản, tiêu đề, số liệu kinh
              doanh có thể nhận diện shop, thông tin người mua hay dữ liệu người dùng Google,
              và không được tiết lộ cho khách hàng khác. Bạn có thể yêu cầu ngừng sử dụng dữ
              liệu của mình cho mục đích này bất kỳ lúc nào qua email; Juli ngừng áp dụng đối
              với dữ liệu phát sinh từ thời điểm nhận được yêu cầu.
            </p>
            <p>
              8.7. Gợi ý kịch bản, tiêu đề và nội dung được Juli xử lý riêng cho từng shop,
              dựa trên dữ liệu và cách dùng từ ngữ của chính shop đó. Nội dung riêng của shop
              (từ ngữ, kịch bản, tiêu đề, hình ảnh) chỉ dùng để tạo gợi ý cho chính shop đó.
            </p>
            <p>
              8.8. Juli dùng mô hình AI của OpenAI (qua OpenAI API) và một số nhà cung cấp dịch
              vụ khác để vận hành dịch vụ; một số nhà cung cấp xử lý dữ liệu ngoài Việt Nam.
              Danh sách đầy đủ, dữ liệu mỗi bên nhận và các biện pháp bảo vệ nằm ở mục 7 của{" "}
              <a href="/privacy">
                Chính sách bảo mật
              </a>
              .
            </p>
          </LegalSection>

          <LegalSection headingId="dieu-9" num="9." title="Chấm dứt">
            <p>
              Bạn có thể ngừng sử dụng Juli và yêu cầu xoá tài khoản bất kỳ lúc nào. Juli có
              thể tạm ngưng hoặc chấm dứt tài khoản vi phạm các điều khoản này hoặc chính
              sách của sàn. Nếu Juli ngừng cung cấp dịch vụ, chúng tôi sẽ thông báo cho bạn
              ít nhất 30 ngày trước.
            </p>
          </LegalSection>

          <LegalSection headingId="dieu-10" num="10." title="Thay đổi điều khoản">
            <p>
              Khi điều khoản thay đổi, chúng tôi cập nhật ngày ở đầu trang này. Với những
              thay đổi quan trọng, chúng tôi thông báo qua email ít nhất 7 ngày trước khi
              thay đổi có hiệu lực. Việc tiếp tục sử dụng Juli sau thời điểm đó đồng nghĩa
              với việc bạn chấp nhận điều khoản mới.
            </p>
          </LegalSection>

          <LegalSection headingId="dieu-11" num="11." title="Liên hệ">
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
