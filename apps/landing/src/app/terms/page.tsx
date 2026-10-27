import { breadcrumbSchema, buildMetadata, JsonLd } from "../../lib/seo";
import { COMPANY } from "../../lib/site";
import { LegalPage, LegalSection } from "../privacy/legal-template";

export const metadata = buildMetadata("/terms");

const LAST_UPDATED = "27/10/2026";

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
  { id: "dieu-11", label: "11. Giới hạn trách nhiệm" },
  { id: "dieu-12", label: "12. Giải quyết tranh chấp" },
  { id: "dieu-13", label: "13. Điều khoản chung" },
  { id: "dieu-14", label: "14. Liên hệ" },
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
              . Nếu bạn sử dụng Juli thay mặt một doanh nghiệp hoặc hộ kinh doanh, bạn xác
              nhận mình có quyền chấp nhận các điều khoản này thay cho doanh nghiệp hoặc hộ
              kinh doanh đó.
            </p>
            <p id="chi-danh-cho-kinh-doanh">
              Juli là dịch vụ dành cho doanh nghiệp, hộ kinh doanh và người bán hàng sử dụng
              vì mục đích kinh doanh, thương mại. Bạn xác nhận bạn sử dụng Juli để vận hành
              hoạt động kinh doanh của mình, không phải với tư cách người tiêu dùng cho mục
              đích sinh hoạt cá nhân, gia đình.
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
              thể huỷ bất cứ lúc nào. Phí đã thanh toán không thể hoàn lại trong mọi trường
              hợp.
            </p>
          </LegalSection>

          <LegalSection headingId="dieu-6" num="6." title="Đề xuất của Juli">
            <p>
              Các đề xuất của Juli được tạo bằng AI dựa trên dữ liệu shop và chỉ mang tính
              tương đối. Juli chỉ thực hiện một hành động khi bạn đồng ý, và bạn là người
              quyết định cuối cùng cho mọi hành động trên shop của mình. Bạn tự chịu trách
              nhiệm về việc áp dụng đề xuất vào hoạt động kinh doanh, kể cả việc tuân thủ chính
              sách của sàn và pháp luật. Nếu Juli tạo hình ảnh, video hoặc âm thanh bằng AI,
              nội dung đó được gắn dấu hiệu nhận biết theo Luật Trí tuệ nhân tạo và bạn không
              được gỡ bỏ dấu hiệu này.
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
              dữ liệu Juli nhận từ sàn (TikTok Shop, Shopee) qua kết nối bạn cho phép để cung
              cấp dịch vụ cho chính shop của bạn, theo{" "}
              <a href="/privacy">
                Chính sách bảo mật
              </a>{" "}
              và điều khoản của sàn.
            </p>
            <p>
              8.2. Bạn bảo đảm mình có quyền cho phép Juli xử lý dữ liệu shop của bạn, bao
              gồm dữ liệu cá nhân của người mua có trong đó, và việc cho phép này phù hợp với
              chính sách của sàn (TikTok Shop, Shopee) và pháp luật về bảo vệ dữ liệu cá nhân
              (Luật Bảo vệ dữ liệu cá nhân số 91/2025/QH15 và Nghị định 356/2025/NĐ-CP).
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
                khác và không bao giờ dùng để huấn luyện bất kỳ mô hình AI nào;
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
              8.6. Dữ liệu từ sàn chỉ phục vụ shop của bạn: Juli không gộp dữ liệu shop hay dữ
              liệu kinh doanh của bạn với dữ liệu của shop khác, không dùng dữ liệu đó để phục
              vụ khách hàng khác, và không bán hay chia sẻ dữ liệu đó. Để cải thiện dịch vụ
              chung, Juli dùng dữ liệu thị trường công khai và dữ liệu của chính Juli; nếu sau
              này Juli muốn dùng dữ liệu của bạn cho mục đích khác, Juli sẽ xin sự đồng ý riêng
              của bạn và chỉ làm khi điều khoản của sàn cho phép. Dữ liệu của người mua và dữ
              liệu người dùng Google không bao giờ được dùng để huấn luyện mô hình.
            </p>
            <p>
              8.7. Gợi ý kịch bản, tiêu đề và nội dung được Juli xử lý riêng cho từng shop,
              dựa trên dữ liệu và cách dùng từ ngữ của chính shop đó. Nội dung riêng của shop
              (từ ngữ, kịch bản, tiêu đề, hình ảnh) không được hiển thị cho shop khác và không
              được dùng để tạo gợi ý cho shop khác.
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
              9.1. Bạn có thể ngừng sử dụng Juli và yêu cầu xoá tài khoản bất kỳ lúc nào, trong
              phần Cài đặt, Quyền riêng tư của ứng dụng hoặc qua email. Sau khi bạn yêu cầu xoá
              tài khoản, bạn có 30 ngày để tải dữ liệu của mình; sau thời hạn này, Juli xoá dữ
              liệu tài khoản, dữ liệu shop và dữ liệu kinh doanh của bạn, trừ dữ liệu pháp luật
              yêu cầu lưu giữ (ví dụ: hoá đơn, chứng từ kế toán của Juli).
            </p>
            <p>
              9.2. Juli chỉ tạm ngưng hoặc chấm dứt tài khoản của bạn, ngay lập tức và không
              hoàn phí, khi bạn:
            </p>
            <ul aria-label="Trường hợp Juli tạm ngưng hoặc chấm dứt tài khoản">
              <li>(a) vi phạm các điều khoản này, bao gồm mục 7;</li>
              <li>
                (b) vi phạm chính sách của sàn (TikTok Shop, Shopee) hoặc dùng Juli cho hàng
                hoá, dịch vụ, hoạt động vi phạm pháp luật;
              </li>
              <li>(c) không thanh toán phí đúng hạn sau khi đã được nhắc;</li>
              <li>(d) cung cấp thông tin giả mạo hoặc kết nối shop không thuộc quyền của bạn;</li>
              <li>(e) là đối tượng của yêu cầu từ cơ quan nhà nước có thẩm quyền.</li>
            </ul>
            <p>
              9.3. Nếu Juli ngừng cung cấp dịch vụ, chúng tôi sẽ thông báo cho bạn ít nhất 30
              ngày trước. Juli có thể thay đổi, bổ sung hoặc ngừng từng tính năng riêng lẻ; với
              thay đổi làm giảm đáng kể tính năng bạn đang dùng, chúng tôi thông báo trước qua
              email hoặc trong ứng dụng.
            </p>
          </LegalSection>

          <LegalSection headingId="dieu-10" num="10." title="Thay đổi điều khoản">
            <p>
              Khi điều khoản thay đổi, chúng tôi cập nhật ngày ở đầu trang này và thông báo qua
              email và trong ứng dụng ít nhất 15 ngày trước khi thay đổi có hiệu lực. Nếu bạn
              không đồng ý, bạn có thể ngừng sử dụng Juli trước ngày có hiệu lực. Việc tiếp tục
              sử dụng Juli sau thời điểm đó đồng nghĩa với việc bạn chấp nhận điều khoản mới.
            </p>
          </LegalSection>

          <LegalSection headingId="dieu-11" num="11." title="Giới hạn trách nhiệm">
            <p>
              11.1. Trong phạm vi tối đa pháp luật cho phép, Juli không chịu trách nhiệm bồi
              thường dưới bất kỳ hình thức nào đối với bất kỳ thiệt hại nào, dù trực tiếp hay
              gián tiếp, phát sinh từ hoặc liên quan đến việc bạn sử dụng hoặc không thể sử dụng
              Juli, kể cả khi Juli đã được thông báo về khả năng xảy ra thiệt hại đó, bao gồm
              nhưng không giới hạn:
            </p>
            <ul aria-label="Thiệt hại Juli không bồi thường">
              <li>(a) lợi nhuận, doanh thu, doanh số hoặc khoản lợi dự kiến bị mất;</li>
              <li>(b) chi phí quảng cáo, khuyến mại, mã giảm giá, vận chuyển hoặc tồn kho;</li>
              <li>
                (c) việc gian hàng bị sàn cảnh cáo, trừ điểm, hạn chế, tạm khoá hoặc khoá;
              </li>
              <li>(d) mất uy tín, khách hàng hoặc cơ hội kinh doanh;</li>
              <li>(e) mất mát, sai lệch hoặc rò rỉ dữ liệu, gián đoạn hoặc lỗi của dịch vụ;</li>
              <li>(f) hậu quả của việc áp dụng đề xuất hoặc nội dung do AI tạo ra;</li>
              <li>(g) chi phí mua dịch vụ thay thế.</li>
            </ul>
            <p>
              11.2. Juli được cung cấp theo hiện trạng và theo khả năng sẵn có. Juli không bảo
              đảm dịch vụ hoạt động liên tục, không có lỗi, hay đạt được kết quả kinh doanh cụ
              thể nào. Juli không chịu trách nhiệm về hoạt động, thay đổi hay quyết định của các
              bên thứ ba, bao gồm sàn thương mại điện tử và các nhà cung cấp nêu tại mục 7 của{" "}
              <a href="/privacy">
                Chính sách bảo mật
              </a>
              , và về sự kiện bất khả kháng (thiên tai, dịch bệnh, sự cố hạ tầng mạng hoặc
              điện, tấn công mạng, quyết định của cơ quan nhà nước).
            </p>
            <p>
              11.3. Bạn xác nhận đã đọc, hiểu và đồng ý riêng với Điều 11 này khi đăng ký hoặc
              tiếp tục sử dụng Juli, và đây là thoả thuận của các bên về các trường hợp miễn
              trách nhiệm.
            </p>
          </LegalSection>

          <LegalSection headingId="dieu-12" num="12." title="Giải quyết tranh chấp">
            <p>
              Các điều khoản này được điều chỉnh bởi pháp luật Việt Nam. Bạn gửi khiếu nại tới
              email bên dưới; Juli xác nhận đã nhận trong 2 ngày làm việc. Tranh chấp được ưu
              tiên giải quyết bằng thương lượng trong 30 ngày kể từ ngày một bên gửi yêu cầu.
              Nếu không thương lượng được, tranh chấp được giải quyết tại Toà án có thẩm quyền
              nơi Juli đặt trụ sở.
            </p>
          </LegalSection>

          <LegalSection headingId="dieu-13" num="13." title="Điều khoản chung">
            <p>
              Nếu bất kỳ phần nào của các điều khoản này bị tuyên vô hiệu hoặc không thể thực
              thi, phần đó được thực hiện ở mức tối đa pháp luật cho phép, và các phần còn lại
              vẫn giữ nguyên hiệu lực. Các điều khoản này và{" "}
              <a href="/privacy">
                Chính sách bảo mật
              </a>{" "}
              là toàn bộ thoả thuận giữa bạn và Juli về dịch vụ. Nếu bạn đã ký hợp đồng riêng
              với Juli, hợp đồng đó được ưu tiên áp dụng khi có khác biệt.
            </p>
          </LegalSection>

          <LegalSection headingId="dieu-14" num="14." title="Liên hệ">
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
