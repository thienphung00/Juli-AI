import type { Metadata } from "next";

import { LandingHeader } from "../../components/landing-header";
import { SiteFooter } from "../../components/site-footer";
import { COMPANY } from "../../lib/site";

export const metadata: Metadata = {
  title: "Điều khoản dịch vụ — Juli AI",
  description:
    "Điều khoản sử dụng Juli AI, trợ lý tăng trưởng và tối ưu vận hành cho người bán TikTok Shop và Shopee.",
};

const VERSION = "2.0";
const LAST_UPDATED = "14/10/2026";

function PrivacyLink() {
  return (
    <a className="lp-legal__contact-link" href="/privacy">
      Chính sách bảo mật
    </a>
  );
}

export default function TermsOfServicePage() {
  return (
    <>
      <LandingHeader />
      <main className="lp-main">
        <article className="lp-legal">
          <p className="lp-legal__eyebrow">Pháp lý</p>
          <h1 className="lp-legal__heading">Điều khoản dịch vụ</h1>
          <p className="lp-legal__updated">
            Phiên bản: {VERSION} — Cập nhật lần cuối: {LAST_UPDATED}
          </p>

          <section className="lp-legal__section">
            <h2 className="lp-legal__section-heading">1. Giới thiệu</h2>
            <p>
              Juli AI (&quot;Juli&quot;) là dịch vụ do {COMPANY.name} (mã số thuế{" "}
              {COMPANY.taxId}, trụ sở tại {COMPANY.address}) cung cấp. Bằng việc đăng nhập
              hoặc sử dụng Juli, bạn đồng ý với các điều khoản này và với <PrivacyLink />.
              Nếu bạn sử dụng Juli thay mặt một doanh nghiệp hoặc hộ kinh doanh, bạn xác
              nhận mình có quyền chấp nhận các điều khoản này thay cho doanh nghiệp hoặc hộ
              kinh doanh đó, và &quot;bạn&quot; trong điều khoản này bao gồm cả doanh nghiệp
              hoặc hộ kinh doanh đó.
            </p>
          </section>

          <section className="lp-legal__section">
            <h2 className="lp-legal__section-heading">2. Juli AI là gì</h2>
            <p>
              Juli AI (tên gọi khác JustLiveAI) là trợ lý giúp người bán trên TikTok Shop và
              Shopee tăng trưởng và tối ưu vận hành: theo dõi shop, phân tích dữ liệu (đơn
              hàng, sản phẩm, tồn kho, đơn hoàn, hiệu suất theo từng luồng truy cập) và đề
              xuất hành động phù hợp. Bạn phê duyệt, Juli mới thực hiện, Juli không tự động
              thay đổi shop thật của bạn nếu chưa có sự đồng ý của bạn, và mỗi thao tác trên
              shop thật (ví dụ: tạo mã giảm giá) chỉ được thực hiện đúng sản phẩm và đúng loại
              thao tác bạn đã phê duyệt, theo mục 5 của <PrivacyLink />.
            </p>
          </section>

          <section className="lp-legal__section">
            <h2 className="lp-legal__section-heading">3. Tài khoản của bạn</h2>
            <p>
              Bạn phải từ 18 tuổi trở lên để sử dụng Juli. Bạn tạo và truy cập tài khoản
              Juli bằng cách đăng nhập với Google hoặc bằng email với mã xác thực. Bạn chịu
              trách nhiệm bảo mật tài khoản Google và hộp thư email của mình; mọi hoạt động
              qua tài khoản đã đăng nhập được xem là hoạt động của bạn.
            </p>
          </section>

          <section className="lp-legal__section">
            <h2 className="lp-legal__section-heading">4. Kết nối shop</h2>
            <p>
              4.1. Bạn kết nối shop với Juli bằng một trong hai cách nêu tại mục 4 của{" "}
              <PrivacyLink />: (a) ủy quyền chính thức qua API của sàn, hoặc (b) cấp cho Juli
              một tài khoản phụ trong Kênh Người Bán của sàn. Khi kết nối, bạn cho phép Juli
              đọc dữ liệu shop của bạn để tạo đề xuất.
            </p>
            <p>
              4.2. Bạn xác nhận mình là chủ shop hoặc được chủ shop uỷ quyền kết nối. Khi cấp
              tài khoản phụ, bạn tự chọn phạm vi quyền của tài khoản đó; Juli khuyến nghị chỉ
              cấp các quyền cần thiết cho việc phân tích. Juli bảo mật thông tin đăng nhập
              tài khoản phụ và chỉ dùng tài khoản này để phục vụ shop của bạn.
            </p>
            <p>
              4.3. Bạn có thể ngắt kết nối hoặc khoá tài khoản phụ bất kỳ lúc nào; khi đó
              Juli ngừng đồng bộ dữ liệu mới và không thể tiếp tục cung cấp dịch vụ cho shop
              đó.
            </p>
          </section>

          <section className="lp-legal__section">
            <h2 className="lp-legal__section-heading">5. Hợp đồng</h2>
            <p>
              5.1. Các điều khoản này, cùng với Xác nhận đơn hàng Juli gửi cho bạn khi bạn
              thanh toán (ghi gói dịch vụ, kỳ sử dụng và phí), tạo thành hợp đồng cung cấp
              dịch vụ giữa bạn và {COMPANY.name}. Hợp đồng được giao kết bằng phương tiện điện
              tử và có giá trị như hợp đồng bằng văn bản theo pháp luật về giao dịch điện tử.
            </p>
            <p>
              5.2. Nếu bạn cần hợp đồng có chữ ký, Juli cung cấp mẫu Hợp đồng kiêm đơn đặt
              hàng (hoặc Hợp đồng hợp tác thử nghiệm cho chương trình Pilot). Nếu hợp đồng có
              chữ ký khác với các điều khoản này, hợp đồng có chữ ký được ưu tiên áp dụng;
              những nội dung hợp đồng đó không quy định thì áp dụng các điều khoản này và{" "}
              <PrivacyLink />.
            </p>
          </section>

          <section className="lp-legal__section">
            <h2 className="lp-legal__section-heading">
              6. Phí dịch vụ, thanh toán và hoá đơn
            </h2>
            <p>
              6.1. Phí dịch vụ Juli là 500.000đ/tháng, đã bao gồm thuế giá trị gia tăng (nếu
              có). Phí được thanh toán trước cho mỗi kỳ sử dụng.
            </p>
            <p>6.2. Bạn thanh toán bằng chuyển khoản ngân hàng.</p>
            <p>
              6.3. Kỳ sử dụng tự động gia hạn với cùng thời hạn, trừ khi bạn huỷ gia hạn
              trước ngày bắt đầu kỳ tiếp theo. Mỗi kỳ gia hạn, Juli gửi Xác nhận đơn hàng và
              hoá đơn mới qua email; hai bên không cần ký lại hợp đồng.
            </p>
            <p>
              6.4. Juli xuất hoá đơn điện tử khi nhận được thanh toán, theo thông tin xuất
              hoá đơn bạn cung cấp. Bạn chịu trách nhiệm về tính chính xác của thông tin này.
            </p>
            <p>
              6.5. Bạn có thể huỷ gia hạn bất cứ lúc nào. Sau khi huỷ, bạn vẫn tiếp tục sử
              dụng Juli đến hết kỳ đã thanh toán, và có thể ngắt kết nối shop bất kỳ lúc nào.
              Phí đã thanh toán không được hoàn lại.
            </p>
          </section>

          <section className="lp-legal__section">
            <h2 className="lp-legal__section-heading">7. Nghiệm thu</h2>
            <p>
              Dịch vụ của mỗi kỳ được coi là đã được cung cấp và nghiệm thu khi tài khoản của
              bạn được kích hoạt cho kỳ đó. Xác nhận đơn hàng, hoá đơn và chứng từ thanh toán
              là căn cứ xác nhận việc cung cấp và nghiệm thu dịch vụ; hai bên không cần lập
              biên bản nghiệm thu, trừ khi có thoả thuận khác bằng văn bản.
            </p>
          </section>

          <section className="lp-legal__section">
            <h2 className="lp-legal__section-heading">8. Đề xuất của Juli</h2>
            <p>
              Các đề xuất của Juli được tạo bằng AI dựa trên dữ liệu shop và chỉ mang tính
              tương đối. Juli chỉ thực hiện một hành động khi bạn đồng ý, và bạn là người
              quyết định cuối cùng cho mọi hành động trên shop của mình.
            </p>
          </section>

          <section className="lp-legal__section">
            <h2 className="lp-legal__section-heading">9. Sử dụng hợp lệ</h2>
            <p>
              Bạn đồng ý không sử dụng Juli để vi phạm pháp luật hoặc chính sách của sàn
              (TikTok Shop, Shopee), không truy cập trái phép vào hệ thống hay dữ liệu của
              người khác, và không sao chép, dịch ngược hoặc khai thác Juli ngoài mục đích vận
              hành shop của bạn.
            </p>
          </section>

          <section className="lp-legal__section">
            <h2 className="lp-legal__section-heading">10. Dữ liệu của bạn</h2>
            <p>
              10.1. Dữ liệu shop và dữ liệu kinh doanh của bạn thuộc về bạn. Juli chỉ xử lý
              dữ liệu đó để cung cấp dịch vụ cho bạn, theo <PrivacyLink />.
            </p>
            <p>
              10.2. Với dữ liệu cá nhân của người mua có trong dữ liệu shop (ví dụ: mã định
              danh người mua trong đơn hàng), bạn là bên kiểm soát dữ liệu và Juli là bên xử
              lý dữ liệu thay mặt bạn. Juli cam kết:
            </p>
            <ul aria-label="Cam kết của Juli với dữ liệu người mua">
              <li>(a) chỉ xử lý dữ liệu này theo mục đích cung cấp dịch vụ cho bạn;</li>
              <li>
                (b) áp dụng các biện pháp bảo vệ nêu tại <PrivacyLink /> và chỉ chia sẻ với
                các bên xử lý được liệt kê tại đó;
              </li>
              <li>
                (c) không bán, không tiết lộ và không chuyển giao dữ liệu này cho bất kỳ bên
                thứ ba nào ngoài các bên xử lý được liệt kê tại <PrivacyLink />; không sử dụng
                dữ liệu sai mục đích, bao gồm không dùng để phục vụ khách hàng khác và không
                dùng để huấn luyện mô hình AI tổng quát;
              </li>
              <li>
                (d) chỉ truy cập và xử lý dữ liệu trong phạm vi quyền được cấp và cần thiết
                cho việc cung cấp dịch vụ, tuân thủ nghiêm ngặt các chính sách về truy cập và
                bảo vệ dữ liệu của TikTok Shop và Shopee;
              </li>
              <li>
                (e) thông báo cho bạn chậm nhất 72 giờ sau khi phát hiện sự cố lộ, mất dữ liệu
                ảnh hưởng tới dữ liệu của bạn;
              </li>
              <li>
                (f) khi hợp đồng chấm dứt, xoá dữ liệu trong vòng 30 ngày, và cung cấp bản
                xuất dữ liệu nếu bạn yêu cầu trước khi xoá.
              </li>
            </ul>
            <p>
              10.3. Cải thiện thuật toán: Juli được sử dụng dữ liệu shop đã được ẩn danh hoá,
              chỉ ở dạng cấu trúc dữ liệu (ví dụ: loại chỉ số, mối tương quan giữa các chỉ
              số, loại đề xuất và kết quả sau khi áp dụng) để tối ưu thuật toán phân tích và
              chất lượng gợi ý của Juli, bao gồm tinh chỉnh (fine-tune) mô hình ngôn ngữ của
              bên thứ ba thành mô hình riêng của Juli. Dữ liệu dùng cho mục đích này không
              chứa tên shop, tên hoặc nội dung sản phẩm, hình ảnh, kịch bản, tiêu đề, số liệu
              kinh doanh có thể nhận diện shop, thông tin người mua hay dữ liệu người dùng
              Google, và không được tiết lộ cho khách hàng khác. Bạn có thể yêu cầu ngừng sử
              dụng dữ liệu của mình cho mục đích này bất kỳ lúc nào qua email; Juli ngừng áp
              dụng đối với dữ liệu phát sinh từ thời điểm nhận được yêu cầu.
            </p>
            <p>
              10.4. Gợi ý theo từng shop: gợi ý kịch bản, tiêu đề và nội dung được Juli xử lý
              riêng cho từng shop, dựa trên dữ liệu và cách dùng từ ngữ của chính shop đó.
              Nội dung riêng của shop (từ ngữ, kịch bản, tiêu đề, hình ảnh) chỉ dùng để tạo
              gợi ý cho chính shop đó.
            </p>
            <p>
              10.5. Bạn bảo đảm việc cho phép Juli xử lý dữ liệu người mua là phù hợp với
              chính sách của sàn và pháp luật về bảo vệ dữ liệu cá nhân.
            </p>
          </section>

          <section className="lp-legal__section">
            <h2 className="lp-legal__section-heading">11. Bảo mật thông tin</h2>
            <p>
              Mỗi bên giữ bí mật các thông tin không công khai mà bên kia cung cấp trong quá
              trình sử dụng dịch vụ (bao gồm dữ liệu shop, số liệu kinh doanh, thông tin kỹ
              thuật của Juli), không tiết lộ cho bên thứ ba trừ khi được bên kia đồng ý, theo
              yêu cầu của cơ quan nhà nước có thẩm quyền, hoặc cho các bên xử lý cần thiết để
              vận hành dịch vụ. Nghĩa vụ này tiếp tục có hiệu lực 2 năm sau khi hợp đồng chấm
              dứt.
            </p>
          </section>

          <section className="lp-legal__section">
            <h2 className="lp-legal__section-heading">12. Chấm dứt</h2>
            <p>
              12.1. Bạn có thể ngừng sử dụng Juli và yêu cầu xoá tài khoản bất kỳ lúc nào.
            </p>
            <p>
              12.2. Juli có thể tạm ngưng hoặc chấm dứt tài khoản vi phạm các điều khoản này
              hoặc chính sách của sàn.
            </p>
            <p>
              12.3. Nếu Juli ngừng cung cấp dịch vụ, chúng tôi thông báo cho bạn ít nhất 30
              ngày trước.
            </p>
            <p>
              12.4. Hợp đồng tự chấm dứt khi kỳ sử dụng cuối cùng kết thúc mà không được gia
              hạn, hoặc khi tài khoản bị xoá, và các bên đã hoàn tất nghĩa vụ thanh toán. Hai
              bên không cần lập biên bản thanh lý hợp đồng. Các mục 10, 11, 13 và 15 tiếp tục
              có hiệu lực sau khi hợp đồng chấm dứt.
            </p>
          </section>

          <section className="lp-legal__section">
            <h2 className="lp-legal__section-heading">13. Giới hạn trách nhiệm</h2>
            <p>
              13.1. Juli được cung cấp theo hiện trạng, trên cơ sở nỗ lực hợp lý. Juli không
              bảo đảm dịch vụ không bị gián đoạn. Juli không cam kết và không bảo đảm tăng
              GMV, doanh thu, lợi nhuận hay bất kỳ kết quả kinh doanh cụ thể nào; mọi con số
              ước tính trong đề xuất, báo cáo hoặc trao đổi chỉ mang tính tham khảo.
            </p>
            <p>
              13.2. Mọi hành động trên shop chỉ được thực hiện sau khi bạn (hoặc người đại
              diện, người vận hành được bạn chỉ định) xem, chỉnh sửa (nếu muốn) và phê duyệt.
              Bạn chịu trách nhiệm về nội dung và hậu quả của các hành động bạn đã phê duyệt,
              bao gồm việc tuân thủ chính sách của sàn.
            </p>
            <p>
              13.3. Juli không chịu trách nhiệm đối với thiệt hại gián tiếp, mất lợi nhuận,
              mất doanh thu, hoặc các biện pháp xử lý của sàn đối với shop của bạn.
            </p>
            <p>
              13.4. Tổng trách nhiệm bồi thường của Juli đối với bạn, trong mọi trường hợp,
              không vượt quá phí bạn đã thanh toán cho Juli trong 01 (một) tháng trước sự kiện
              phát sinh trách nhiệm, hoặc 500.000đ (năm trăm nghìn đồng), tuỳ theo số nào lớn
              hơn.
            </p>
            <p>
              13.5. Giới hạn tại mục này không áp dụng đối với thiệt hại do Juli cố ý gây ra,
              hoặc trong trường hợp pháp luật không cho phép giới hạn trách nhiệm.
            </p>
          </section>

          <section className="lp-legal__section">
            <h2 className="lp-legal__section-heading">14. Thay đổi điều khoản</h2>
            <p>
              Mỗi lần điều khoản thay đổi, chúng tôi cập nhật số phiên bản và ngày ở đầu
              trang này và lưu lại các phiên bản trước. Với những thay đổi quan trọng (bao gồm
              thay đổi về phí), chúng tôi thông báo qua email ít nhất 7 ngày trước khi thay
              đổi có hiệu lực. Thay đổi về phí chỉ áp dụng từ kỳ gia hạn tiếp theo. Việc tiếp
              tục sử dụng Juli sau thời điểm có hiệu lực đồng nghĩa với việc bạn chấp nhận
              điều khoản mới.
            </p>
          </section>

          <section className="lp-legal__section">
            <h2 className="lp-legal__section-heading">
              15. Luật áp dụng và giải quyết tranh chấp
            </h2>
            <p>
              Các điều khoản này được điều chỉnh bởi pháp luật Việt Nam. Tranh chấp được ưu
              tiên giải quyết bằng thương lượng trong 30 ngày; nếu không thành, tranh chấp
              được giải quyết tại Toà án nhân dân có thẩm quyền tại Thành phố Hồ Chí Minh.
            </p>
          </section>

          <section className="lp-legal__section">
            <h2 className="lp-legal__section-heading">16. Liên hệ</h2>
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
