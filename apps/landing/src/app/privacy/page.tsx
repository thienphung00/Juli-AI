import { breadcrumbSchema, buildMetadata, JsonLd } from "../../lib/seo";
import { COMPANY } from "../../lib/site";

import { legal, LegalPage, LegalSection } from "./legal-template";
import {
  ENGLISH_SECTION_ID,
  GOOGLE_PERMISSIONS_URL,
  GOOGLE_USER_DATA_POLICY_URL,
  LAST_UPDATED_EN,
  PrivacyPolicyEnglish,
} from "./privacy-policy-english";

export const metadata = buildMetadata("/privacy");

const LAST_UPDATED = "18/10/2026";

/** Anchor for the trial sign-up paragraph in §2 (P33-F), linked from /dang-ky's consent. */
const TRIAL_SIGNUP_SECTION_ID = "dang-ky-dung-thu";

/** Anchor for §3, so the Google OAuth consent screen can deep-link to it. */
const GOOGLE_SECTION_ID = "du-lieu-nguoi-dung-google";

const TOC = [
  { id: "muc-1", label: "1. Chúng tôi là ai" },
  { id: "muc-2", label: "2. Thông tin tài khoản" },
  { id: GOOGLE_SECTION_ID, label: "3. Dữ liệu người dùng Google" },
  { id: "muc-4", label: "4. Dữ liệu đọc từ shop" },
  { id: "shopee-data", label: "4A. Dữ liệu Shopee" },
  { id: "muc-5", label: "5. Thay đổi trên shop" },
  { id: "muc-6", label: "6. Mục đích sử dụng" },
  { id: "muc-7", label: "7. Chia sẻ dữ liệu" },
  { id: "muc-8", label: "8. Bảo mật và lưu trữ" },
  { id: "muc-9", label: "9. Quyền của bạn" },
  { id: "muc-10", label: "10. Độ tuổi sử dụng" },
  { id: "muc-11", label: "11. Thay đổi chính sách" },
  { id: "muc-12", label: "12. Liên hệ" },
  { id: ENGLISH_SECTION_ID, label: "English version" },
  { id: "lien-he-quyen-rieng-tu", label: "Liên hệ về quyền riêng tư" },
] as const;

export default function PrivacyPolicyPage() {
  return (
    <>
      <JsonLd data={breadcrumbSchema("/privacy")} />
      <LegalPage
        contactId="lien-he-quyen-rieng-tu"
        contactTitle="Liên hệ về quyền riêng tư"
        effective={LAST_UPDATED}
        englishHref={`#${ENGLISH_SECTION_ID}`}
        title="Chính sách bảo mật"
        toc={TOC}
        updated={LAST_UPDATED}
      >
          <div className={legal.enNotice} lang="en" data-testid="privacy-en-notice">
            <p>
              <strong>Privacy Policy — Juli AI.</strong> App name: Juli AI. Operator:{" "}
              <span lang="vi">{COMPANY.name}</span> (tax ID {COMPANY.taxId}). Website:
              app-juli.com. Contact:{" "}
              <a href={`mailto:${COMPANY.email}`}>
                {COMPANY.email}
              </a>
              . Last updated (effective date): {LAST_UPDATED_EN}.
            </p>
            <p>
              <a href={`#${ENGLISH_SECTION_ID}`}>
                English version ↓
              </a>
            </p>
          </div>

          <p className={legal.intro}>
            Chính sách này giải thích cách Juli AI thu thập, sử dụng, chia sẻ và bảo vệ dữ
            liệu khi bạn sử dụng website app-juli.com, bản Demo và ứng dụng Juli, phù hợp
            với Luật Bảo vệ dữ liệu cá nhân số 91/2025/QH15 và Nghị định 356/2025/NĐ-CP.
          </p>
          <p className={legal.intro}>
            Trang này có bản tiếng Anh đầy đủ ở phía dưới. Nếu hai bản có khác biệt, bản
            tiếng Việt được ưu tiên áp dụng, trừ trường hợp điều đó mâu thuẫn với các cam
            kết của Juli AI theo Chính sách dữ liệu người dùng của Google API Services, bao
            gồm các yêu cầu Sử dụng giới hạn (Limited Use) tại mục 3 — các cam kết này luôn
            được áp dụng.
          </p>

          <LegalSection headingId="muc-1" num="1." title="Chúng tôi là ai">
            <p>
              Juli AI được vận hành bởi {COMPANY.name} (mã số thuế {COMPANY.taxId}), trụ sở
              tại {COMPANY.address}. {COMPANY.name} là bên kiểm soát và xử lý dữ liệu cá
              nhân được mô tả trong chính sách này. Riêng đối với dữ liệu cá nhân của người
              mua có trong dữ liệu shop, người bán là bên kiểm soát dữ liệu và Juli xử lý dữ
              liệu đó thay mặt người bán, theo mục 8 của{" "}
              <a href="/terms">
                Điều khoản dịch vụ
              </a>
              . Với dữ liệu đã khử định danh mà Juli dùng để cải thiện mô hình của mình (mục
              6), Juli là bên kiểm soát dữ liệu.
            </p>
            <p>
              Bạn có thể liên hệ chúng tôi qua email{" "}
              <a href={`mailto:${COMPANY.email}`}>
                {COMPANY.email}
              </a>
              .
            </p>
          </LegalSection>

          <LegalSection headingId="muc-2" num="2." title="Thông tin tài khoản">
            <p>
              Bạn tạo và truy cập tài khoản Juli bằng cách đăng nhập với Google, hoặc bằng
              email với mã xác thực gửi tới hộp thư của bạn (thông qua Supabase Auth). Chúng
              tôi không yêu cầu bạn tạo hoặc nhập mật khẩu.
            </p>
            <ul aria-label="Thông tin tài khoản Juli thu thập">
              <li>
                Từ Google: địa chỉ email, tên hiển thị, ảnh đại diện và mã định danh tài
                khoản Google (xem mục 3)
              </li>
              <li>Khi đăng nhập bằng email: địa chỉ email bạn nhập</li>
              <li>
                Tuỳ chọn: số Zalo hoặc mã người dùng Zalo, chỉ khi bạn bật nhận cảnh báo
                qua Zalo
              </li>
              <li>
                Tuỳ chọn: mã thiết bị, chỉ khi bạn bật thông báo đẩy trên điện thoại
              </li>
            </ul>
            <h3 className={legal.subheading} id={TRIAL_SIGNUP_SECTION_ID}>
              Đăng ký dùng thử
            </h3>
            <p data-testid="privacy-trial-signup">
              Khi bạn đăng ký dùng thử tại trang <a href="/dang-ky">Đăng ký dùng thử</a>, chúng
              tôi thu thập họ tên, số điện thoại/Zalo, email, tên hoặc đường dẫn shop TikTok,
              vai trò của bạn, ghi chú bạn viết (nếu có), nguồn truy cập (tham số utm và trang
              giới thiệu) và thời điểm bạn đồng ý. Chúng tôi không lưu địa chỉ IP của bạn, chỉ
              lưu một mã băm của nó để chống gửi lặp và spam. Mục đích duy nhất là liên hệ với
              bạn và thiết lập kết nối shop cho đợt dùng thử; chỉ đội ngũ Juli xem được thông
              tin này, và nhà cung cấp gửi email của chúng tôi chuyển thông báo đăng ký tới đội
              ngũ. Nếu bạn không bắt đầu dùng Juli, thông tin được lưu tối đa 12 tháng kể từ
              ngày đăng ký rồi xoá; nếu bạn dùng Juli, thông tin trở thành thông tin tài khoản
              theo chính sách này. Bạn có thể yêu cầu xoá bất cứ lúc nào qua{" "}
              <a href={`mailto:${COMPANY.email}`}>
                {COMPANY.email}
              </a>
              ; chúng tôi xoá trong vòng 20 ngày.
            </p>
          </LegalSection>

          <LegalSection headingId="google-user-data-heading" num="3." sectionId={GOOGLE_SECTION_ID} title="Dữ liệu người dùng Google (Google user data)">
            <p>
              Mục này áp dụng khi bạn chọn &ldquo;Đăng nhập với Google&rdquo; trên Juli AI
              (app-juli.com và demo.app-juli.com), do {COMPANY.name} vận hành. Việc đăng
              nhập được thực hiện qua Supabase Auth. Juli chỉ yêu cầu các quyền đăng nhập cơ
              bản của Google: <strong>openid</strong>, <strong>email</strong> và{" "}
              <strong>profile</strong>. Juli không yêu cầu quyền truy cập Gmail, Google
              Drive, Danh bạ, Lịch hay bất kỳ dịch vụ hoặc dữ liệu Google nào khác.
            </p>

            <h3 className={legal.subheading}>3.1. Dữ liệu Juli truy cập</h3>
            <ul aria-label="Dữ liệu người dùng Google Juli truy cập">
              <li>Địa chỉ email của tài khoản Google và trạng thái đã xác thực của email đó</li>
              <li>Tên hiển thị (họ tên) trên tài khoản Google</li>
              <li>Ảnh đại diện (đường dẫn ảnh hồ sơ) trên tài khoản Google</li>
              <li>Mã định danh tài khoản Google (Google account ID)</li>
            </ul>
            <p>
              Juli không nhận mật khẩu Google của bạn. Juli không lưu mã truy cập (access
              token) hay mã làm mới (refresh token) Google của bạn, và không gọi bất kỳ API
              Google nào thay mặt bạn sau khi đăng nhập.
            </p>

            <h3 className={legal.subheading}>3.2. Cách Juli sử dụng dữ liệu này</h3>
            <ul aria-label="Cách Juli sử dụng dữ liệu người dùng Google">
              <li>Tạo tài khoản Juli cho bạn và đăng nhập cho bạn ở những lần sau</li>
              <li>
                Nhận diện tài khoản của bạn, để mỗi tài khoản chỉ xem được shop và dữ liệu của
                chính mình, và hiển thị email bạn đang đăng nhập trong ứng dụng
              </li>
              <li>Liên hệ với bạn về tài khoản và dịch vụ Juli (ví dụ: hỗ trợ, thay đổi quan trọng)</li>
            </ul>
            <p>
              Juli chỉ dùng dữ liệu người dùng Google để cung cấp và cải thiện các tính năng
              của Juli mà bạn thấy và sử dụng. Juli <strong>không</strong> dùng dữ liệu này
              cho quảng cáo (kể cả quảng cáo nhắm mục tiêu, cá nhân hoá hay tiếp thị lại),
              <strong> không</strong> bán dữ liệu này, <strong>không</strong> dùng để đánh giá
              tín dụng hay cho vay, và <strong>không</strong> dùng để phát triển, cải thiện
              hay huấn luyện các mô hình trí tuệ nhân tạo (AI) hoặc học máy (ML) tổng quát.
              Dữ liệu người dùng Google cũng không được dùng để huấn luyện bất kỳ mô hình nào
              của Juli.
              Dữ liệu người dùng Google không được gửi cho OpenAI hay bất kỳ mô hình AI nào.
              Nhân viên Juli không đọc dữ liệu này, trừ khi bạn đồng ý (ví dụ: khi bạn nhờ hỗ
              trợ, hoặc để hỗ trợ và vận hành dịch vụ — bạn đồng ý điều này khi kết nối shop),
              khi cần cho mục đích bảo mật (ví dụ: điều tra lạm dụng), hoặc khi pháp luật yêu
              cầu. Nhân viên chỉ xem dữ liệu shop, không bao giờ xem dữ liệu người mua, và mọi
              lần truy cập đều được ghi nhật ký.
            </p>
            <p>
              Việc Juli sử dụng và chuyển cho bất kỳ ứng dụng nào khác thông tin nhận được từ
              Google API tuân thủ{" "}
              <a
                href={GOOGLE_USER_DATA_POLICY_URL}
                rel="noopener noreferrer"
                target="_blank"
              >
                Chính sách dữ liệu người dùng của Google API Services (Google API Services
                User Data Policy)
              </a>
              , bao gồm các yêu cầu về Sử dụng giới hạn (Limited Use).
            </p>

            <h3 className={legal.subheading}>3.3. Juli chia sẻ dữ liệu này với ai</h3>
            <p>
              Juli không bán, không cho thuê và không trao đổi dữ liệu người dùng Google. Juli
              chỉ chuyển hoặc tiết lộ dữ liệu này trong các trường hợp sau:
            </p>
            <ul aria-label="Bên nhận dữ liệu người dùng Google">
              <li>
                Nhà cung cấp dịch vụ cần thiết để vận hành Juli, chỉ trong phạm vi cần thiết:
                Supabase (xác thực đăng nhập và lưu trữ cơ sở dữ liệu của Juli), nhà cung cấp
                máy chủ (VPS) nơi chạy ứng dụng Juli, và Google Workspace (dịch vụ email Juli
                dùng để gửi mã đăng nhập và thư liên hệ về tài khoản cho bạn)
              </li>
              <li>Khi pháp luật hoặc cơ quan nhà nước có thẩm quyền yêu cầu</li>
              <li>Khi có sự đồng ý rõ ràng của bạn</li>
            </ul>
            <p>
              Juli không gửi dữ liệu người dùng Google cho nền tảng quảng cáo nào (kể cả
              TikTok Pixel và TikTok Events API), không gửi cho nhà môi giới dữ liệu, và không
              chuyển dữ liệu này cho bên nào khác vì bất kỳ mục đích nào ngoài các mục đích
              nêu trên.
            </p>

            <h3 className={legal.subheading}>3.4. Cách Juli bảo vệ dữ liệu này</h3>
            <ul aria-label="Cách Juli bảo vệ dữ liệu người dùng Google">
              <li>
                Mã hoá khi truyền: kết nối giữa trình duyệt của bạn và Juli, và giữa máy chủ
                Juli với Supabase, đều được mã hoá bằng HTTPS/TLS
              </li>
              <li>
                Cơ sở dữ liệu được lưu trữ trên Supabase, nơi dữ liệu được mã hoá khi lưu trữ
                (encryption at rest) bởi nhà cung cấp
              </li>
              <li>
                Kiểm soát truy cập: mỗi yêu cầu tới máy chủ Juli phải kèm phiên đăng nhập đã
                được xác minh chữ ký; cơ sở dữ liệu áp dụng phân quyền theo từng dòng (row-level
                security) để mỗi tài khoản chỉ đọc được dữ liệu của chính mình; ứng dụng chạy
                bằng tài khoản cơ sở dữ liệu với quyền tối thiểu cần thiết
              </li>
              <li>
                Khoá bí mật của hệ thống được lưu trong dịch vụ quản lý khoá bí mật (AWS), không
                lưu trong mã nguồn
              </li>
              <li>
                Trình duyệt của bạn chỉ lưu phiên đăng nhập Juli (do Supabase cấp), không lưu mã
                truy cập Google; phiên này bị xoá khi bạn đăng xuất
              </li>
            </ul>

            <h3 className={legal.subheading}>3.5. Lưu trữ, xoá dữ liệu và thu hồi quyền truy cập</h3>
            <ul aria-label="Lưu trữ và xoá dữ liệu người dùng Google">
              <li>
                Lưu trữ: Juli giữ dữ liệu người dùng Google nêu ở mục 3.1 trong thời gian tài
                khoản Juli của bạn còn tồn tại
              </li>
              <li>
                Yêu cầu xoá: gửi email tới{" "}
                <a href={`mailto:${COMPANY.email}`}>
                  {COMPANY.email}
                </a>{" "}
                từ địa chỉ email của tài khoản, hoặc dùng nút Xoá tài khoản trong Cài đặt, mục
                Quyền riêng tư. Chúng tôi phản hồi trong 2 ngày làm việc. Khi bạn xoá tài khoản,
                tài khoản cùng toàn bộ dữ liệu người dùng Google được xoá khỏi hệ thống của Juli
                và Supabase sau 30 ngày để bạn kịp tải dữ liệu; nếu bạn yêu cầu xoá ngay, chúng
                tôi xoá trong vòng 20 ngày kể từ khi nhận yêu cầu
              </li>
              <li>
                Thu hồi quyền truy cập: bạn có thể gỡ quyền truy cập của Juli bất kỳ lúc nào tại{" "}
                <a
                  href={GOOGLE_PERMISSIONS_URL}
                  rel="noopener noreferrer"
                  target="_blank"
                >
                  trang quyền của tài khoản Google
                </a>{" "}
                (myaccount.google.com/permissions). Sau khi thu hồi, Juli không thể đăng nhập
                cho bạn bằng Google nữa. Việc thu hồi không tự động xoá dữ liệu Juli đã lưu;
                để xoá, hãy gửi yêu cầu xoá như trên
              </li>
            </ul>
          </LegalSection>

          <LegalSection headingId="muc-4" num="4." title="Thông tin chúng tôi đọc từ shop của bạn">
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
              người mua ngoài mã định danh cần thiết để xử lý đơn hàng.
            </p>

            <h3 className={legal.subheading} id="noi-dung-ban-cung-cap">
              Nội dung bạn tự cung cấp
            </h3>
            <p>
              Ngoài dữ liệu đọc từ sàn, Juli xử lý nội dung bạn chủ động nhập hoặc tải lên:
              Quy tắc của shop (ví dụ: giá vốn, biên lợi nhuận, giọng văn, từ không được dùng)
              và video hoặc bản ghi LIVE bạn tải lên để Juli phân tích nội dung. File bạn tải
              lên được lưu tạm trên máy chủ của Juli và xoá khi phân tích kết thúc; file còn
              lại (ví dụ: tải lên dở dang) được xoá tự động sau khoảng 24 giờ. Juli chỉ giữ
              kết quả phân tích (ví dụ: lời thoại đã chuyển thành văn bản, điểm đánh giá). Bạn
              bảo đảm mình có quyền với nội dung này, bao gồm sự đồng ý của những người xuất
              hiện trong đó (mục 8.4 của <a href="/terms">Điều khoản dịch vụ</a>).
            </p>

            <h3 className={legal.subheading} id="danh-gia-va-du-lieu-thi-truong">
              Đánh giá của người mua và dữ liệu thị trường
            </h3>
            <p>
              Nếu Juli sử dụng nội dung đánh giá sản phẩm của người mua (ví dụ: để hiểu cách
              người mua mô tả sản phẩm), Juli loại bỏ tên và thông tin định danh của người mua
              trước khi xử lý, kể cả trước khi gửi cho mô hình AI.
            </p>
            <p>
              Dữ liệu thị trường và đối thủ (ví dụ: giá bán, sản phẩm và video bán chạy theo
              ngành hàng, từ khoá) được Juli lấy từ nguồn công khai và từ nhà cung cấp dữ liệu
              thị trường TikTok Shop là FastMoss. Đây là dữ liệu Juli tự thu thập, không lấy
              từ dữ liệu riêng của các shop khác dùng Juli. Juli không gửi dữ liệu shop của
              bạn (đơn hàng, số liệu kinh doanh, dữ liệu người mua) cho FastMoss; khi tra cứu,
              Juli chỉ dùng thông tin đã công khai trên TikTok Shop, như tên shop hoặc sản
              phẩm.
            </p>
          </LegalSection>

          <LegalSection headingId="shopee-data-heading" num="4A." sectionId="shopee-data" title="Dữ liệu Shopee (khi bạn kết nối shop Shopee)">
            <p>
              Shopee đang được tích hợp qua Shopee Open Platform. Mục này có hiệu lực từ khi
              bạn kết nối một shop Shopee với Juli; trước đó Juli không đọc dữ liệu nào từ
              Shopee.
            </p>
            <p>
              Sau khi bạn kết nối và cấp quyền, Juli đọc qua Shopee Open Platform: thông tin
              shop, sản phẩm/danh sách sản phẩm, đơn hàng và các số liệu hiệu suất cần thiết
              để phân tích và đưa ra đề xuất cho shop của bạn, tương tự dữ liệu TikTok Shop ở
              mục 4. Thông tin cá nhân của người mua chỉ được xử lý trong phạm vi cần thiết
              để xử lý đơn hàng, và nhân viên Juli chỉ thấy dữ liệu shop, không xem
              dữ liệu người mua (mục 3).
            </p>
            <p>
              Mục đích sử dụng và thời gian lưu trữ giống dữ liệu TikTok Shop (mục 6 và 8):
              dữ liệu được lưu trong thời gian bạn sử dụng Juli, ngừng đồng bộ ngay khi bạn
              ngắt kết nối shop, và xoá theo mục 8 khi bạn xoá tài khoản. Juli tuân thủ Chính sách bảo vệ dữ liệu (Data Protection Policy) của
              Shopee Open Platform. Thay đổi trên shop Shopee chỉ được ghi khi bạn đã chủ
              động phê duyệt.
            </p>
          </LegalSection>

          <LegalSection headingId="muc-5" num="5." title="Những gì Juli ghi lại hoặc thay đổi trên shop của bạn">
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
          </LegalSection>

          <LegalSection headingId="muc-6" num="6." title="Mục đích sử dụng dữ liệu">
            <h3 className={legal.subheading}>6.1. Cung cấp dịch vụ</h3>
            <ul>
              <li>Cung cấp, vận hành và bảo mật tài khoản và dịch vụ Juli</li>
              <li>Phân tích hiệu suất shop và tạo đề xuất tối ưu cho shop của bạn</li>
              <li>Gửi cảnh báo và thông báo mà bạn đã bật</li>
              <li>Liên hệ hỗ trợ và thông báo các thay đổi quan trọng về dịch vụ và điều khoản</li>
            </ul>
            <p>
              Gợi ý kịch bản, tiêu đề và nội dung được xử lý riêng cho từng shop, dựa trên dữ
              liệu và cách dùng từ ngữ của chính shop đó; nội dung riêng của shop không được
              hiển thị cho shop khác và không dùng để tạo gợi ý cho shop khác, ngoài việc dùng
              ở dạng đã khử định danh theo mục 6.2.
            </p>

            <h3 className={legal.subheading} id="cai-thien-mo-hinh">
              6.2. Cải thiện thuật toán và mô hình của Juli
            </h3>
            <p>
              Juli sử dụng dữ liệu để phân tích, tối ưu thuật toán, nghiên cứu, huấn luyện,
              tinh chỉnh (fine-tune), kiểm thử và phát triển các mô hình và dịch vụ của Juli,
              theo các nguyên tắc sau:
            </p>
            <ul aria-label="Nguyên tắc dùng dữ liệu để cải thiện Juli">
              <li>
                Chỉ dùng dữ liệu đã khử định danh: dữ liệu shop (mục 4, 4A) và dữ liệu về cách
                bạn dùng Juli được loại bỏ tên shop, mã shop, tên, email, số điện thoại của bạn
                và mọi thông tin có thể xác định bạn, shop của bạn hay bất kỳ cá nhân nào trước
                khi được dùng cho mục đích này.
              </li>
              <li>
                Là điều kiện sử dụng Juli, theo mục 8.6 của{" "}
                <a href="/terms">
                  Điều khoản dịch vụ
                </a>
                . Dữ liệu cá nhân còn xác định được bạn không được dùng để huấn luyện mô hình.
              </li>
              <li>
                Không bao giờ dùng dữ liệu người mua và dữ liệu người dùng Google để huấn luyện
                mô hình. Dữ liệu cá nhân của người mua được ẩn danh trước khi đi vào bất kỳ quy
                trình phân tích nào.
              </li>
              <li>
                Dữ liệu dùng cho mục đích này không được tiết lộ cho khách hàng khác. Dữ liệu đã
                được dùng để huấn luyện không thể tách khỏi mô hình; khi bạn xoá tài khoản, dữ
                liệu gốc được xoá theo mục 8 nhưng Juli không huấn luyện lại các mô hình đó.
              </li>
            </ul>
            <p>
              Theo Nghị định 356/2025/NĐ-CP, dữ liệu về hành vi, thói quen sử dụng dịch vụ trực
              tuyến của một cá nhân là dữ liệu cá nhân nhạy cảm. Juli chỉ dùng dữ liệu này ở
              dạng gắn với bạn để vận hành và hỗ trợ tài khoản của bạn; dữ liệu được khử định
              danh trước khi dùng cho mục đích 6.2.
            </p>

            <h3 className={legal.subheading}>6.3. Tiếp thị và đo lường quảng cáo (bạn có thể từ chối)</h3>
            <ul>
              <li>Gửi thông tin về tính năng mới và ưu đãi của Juli</li>
              <li>Đo lường hiệu quả quảng cáo của Juli trên TikTok</li>
              <li>Nêu tên hoặc logo shop của bạn làm ví dụ khách hàng, chỉ khi bạn bật lựa chọn này</li>
            </ul>
            <p>
              Bạn bật hoặc tắt từng mục trên trong Cài đặt, mục Quyền riêng tư của ứng dụng.
            </p>
            <p>
              Juli chỉ lưu, phân tích và chia sẻ dữ liệu của bạn cho các mục đích trên. Juli
              không bán dữ liệu, và không dùng dữ liệu có thể nhận diện shop của bạn để phục vụ
              khách hàng khác.
            </p>
          </LegalSection>

          <LegalSection headingId="muc-7" num="7." title="Chúng tôi chia sẻ dữ liệu với ai">
            <p>
              Juli không bán dữ liệu của bạn cho bất kỳ bên thứ ba nào, không tiết lộ hay
              chuyển giao dữ liệu của bạn ngoài các bên dưới đây. Chúng tôi chỉ chia sẻ dữ liệu
              với các bên xử lý dữ liệu sau, mỗi bên chỉ nhận phần dữ liệu cần thiết cho vai
              trò của mình:
            </p>
            <ul aria-label="Bên xử lý dữ liệu">
              <li>
                Supabase — xác thực đăng nhập (Google và mã xác thực qua email) và lưu trữ cơ
                sở dữ liệu
              </li>
              <li>
                TikTok Shop API — nguồn dữ liệu shop của bạn; Shopee Open Platform — khi bạn
                kết nối shop Shopee (mục 4A)
              </li>
              <li>
                OpenAI — nhà cung cấp mô hình AI (mô hình ngôn ngữ) mà Juli dùng để phân tích
                dữ liệu shop và tạo đề xuất (xem chi tiết bên dưới)
              </li>
              <li>
                Nhà cung cấp máy chủ (VPS) — nơi chạy ứng dụng Juli và lưu tạm file bạn tải lên
                để phân tích
              </li>
              <li>
                Cloudflare — quản lý tên miền, chuyển tiếp và bảo vệ kết nối (HTTPS) tới
                app-juli.com và các tên miền con; kiểm soát truy cập vào công cụ nội bộ của đội
                ngũ Juli
              </li>
              <li>Amazon Web Services (AWS) — quản lý khoá bí mật của hệ thống</li>
              <li>
                Google Workspace — dịch vụ email Juli dùng để gửi mã đăng nhập, thông báo và
                thư liên hệ cho bạn
              </li>
              <li>
                Zalo (Zalo OA) và Google Firebase (dự kiến) — gửi cảnh báo và thông báo đẩy,
                chỉ khi bạn bật
              </li>
              <li>
                Viettel-CA (dự kiến) — xuất, gửi và lưu trữ hoá đơn điện tử khi bạn thanh toán,
                và chuyển dữ liệu hoá đơn tới cơ quan thuế theo quy định
              </li>
              <li>
                TikTok Pixel và Events API — đo lường hiệu quả quảng cáo. Nhận địa chỉ
                IP, thông tin trình duyệt, trang bạn xem trên website này, và mã định
                danh quảng cáo của TikTok nếu bạn đến từ một quảng cáo. Nếu bạn đăng ký,
                TikTok chỉ nhận mã người dùng Juli đã được băm (SHA-256) — không nhận email
                hay bất kỳ dữ liệu người dùng Google nào
              </li>
            </ul>
            <p>
              FastMoss (mục 4) là nguồn dữ liệu thị trường Juli tra cứu, không phải bên xử lý
              dữ liệu shop của bạn.
            </p>

            <h3 className={legal.subheading} id="nha-cung-cap-ai">
              Dữ liệu gửi cho nhà cung cấp AI (OpenAI)
            </h3>
            <p>
              Juli dùng mô hình của OpenAI qua OpenAI API, dịch vụ dành cho doanh nghiệp và nhà
              phát triển, không qua ứng dụng ChatGPT dành cho người dùng cá nhân. Mô hình cụ
              thể có thể thay đổi giữa các mô hình của OpenAI. Juli chỉ gửi phần dữ liệu cần
              thiết cho từng phân tích:
            </p>
            <ul aria-label="Dữ liệu gửi cho OpenAI">
              <li>
                Thông tin sản phẩm (tên, mô tả, danh mục, giá) và số liệu hiệu suất của shop
              </li>
              <li>Hình ảnh sản phẩm, để kiểm tra hình ảnh có khớp với nội dung sản phẩm</li>
              <li>Quy tắc và nội dung bạn nhập (ví dụ: giọng văn, từ không được dùng)</li>
              <li>
                Với video hoặc bản ghi LIVE bạn tải lên: các khung hình trích ra (ảnh thu nhỏ)
                và các đoạn âm thanh để chuyển giọng nói thành văn bản; Juli không gửi nguyên
                file
              </li>
              <li>
                Nội dung đánh giá của người mua, nếu được sử dụng, sau khi đã loại bỏ thông tin
                định danh người mua
              </li>
            </ul>
            <p>
              Juli không gửi cho OpenAI thông tin liên hệ hay mã định danh của người mua, dữ
              liệu người dùng Google, hay thông tin đăng nhập tài khoản sàn. Theo điều khoản và
              chính sách dữ liệu API của OpenAI, dữ liệu gửi qua API không được OpenAI dùng để
              huấn luyện các mô hình của OpenAI. Juli gửi các yêu cầu phân tích với chế độ lưu
              trữ phản hồi của OpenAI được tắt; theo chính sách dữ liệu API của OpenAI, OpenAI
              vẫn có thể lưu dữ liệu API trong một thời gian giới hạn để giám sát lạm dụng. Mô
              hình tinh chỉnh (nếu có) là mô hình riêng của Juli và chỉ dùng dữ liệu đã khử định
              danh theo mục 6.2. Juli giới hạn phạm vi và mức sử dụng mô hình cho từng shop.
            </p>

            <h3 className={legal.subheading} id="chuyen-du-lieu-ra-nuoc-ngoai">
              Chuyển dữ liệu ra nước ngoài
            </h3>
            {/*
              [cần luật sư xác nhận: căn cứ pháp lý] — the legal basis and any filing
              requirement for cross-border transfer go here once counsel confirms them.
              Do not add a statute number without that confirmation.
            */}
            <p>
              Một số bên xử lý trên (ví dụ: OpenAI, Amazon Web Services) xử lý hoặc lưu dữ
              liệu ngoài Việt Nam, chủ yếu tại Hoa Kỳ, nên dữ liệu có thể được chuyển ra nước
              ngoài. Chúng tôi chỉ chuyển dữ liệu cần thiết cho mục đích nêu tại mục 6, và bảo
              vệ dữ liệu khi chuyển bằng cách: chỉ dùng các nhà cung cấp hoạt động theo điều
              khoản dịch vụ và cam kết bảo vệ dữ liệu của họ; mã hoá dữ liệu khi truyền
              (HTTPS/TLS); chỉ gửi phần dữ liệu cần thiết cho từng việc; và loại bỏ thông tin
              định danh người mua trước khi gửi cho mô hình AI. Chúng tôi cũng có thể cung cấp
              dữ liệu khi cơ quan nhà nước có thẩm quyền yêu cầu theo quy định pháp luật.
            </p>
          </LegalSection>

          <LegalSection headingId="muc-8" num="8." title="Bảo mật và thời gian lưu trữ">
            <p>
              Dữ liệu được mã hoá khi truyền (HTTPS/TLS) và được nhà cung cấp cơ sở dữ liệu
              (Supabase) mã hoá khi lưu trữ. Quyền truy cập dữ liệu được giới hạn theo từng
              tài khoản và từng shop, và khoá truy cập TikTok Shop được lưu trong hệ thống quản
              lý khoá bí mật, không lưu trong mã nguồn. Chi tiết riêng cho dữ liệu người dùng
              Google nằm ở mục 3.4 và 3.5.
            </p>
            <p>
              Nếu phát hiện sự cố lộ hoặc mất dữ liệu ảnh hưởng tới dữ liệu của bạn, Juli
              thông báo cho bạn chậm nhất 72 giờ sau khi phát hiện.
            </p>
            <p>
              Chúng tôi lưu dữ liệu trong thời gian bạn sử dụng Juli. Khi bạn ngắt kết nối
              shop, Juli ngừng đồng bộ dữ liệu mới từ shop đó ngay lập tức. Khi bạn xoá tài
              khoản, Juli ngừng đồng bộ dữ liệu shop và giữ dữ liệu thêm 30 ngày để bạn tải về
              hoặc huỷ yêu cầu; sau đó dữ liệu tài khoản và dữ liệu shop được xoá. Nếu bạn yêu
              cầu xoá ngay, chúng tôi xoá trong vòng 20 ngày. Hoá đơn và chứng từ kế toán được
              lưu 10 năm theo pháp luật kế toán; dữ liệu đã khử định danh theo mục 6.2 không bị
              xoá.
            </p>
          </LegalSection>

          <LegalSection headingId="muc-9" num="9." title="Quyền của bạn">
            <p>Theo Luật Bảo vệ dữ liệu cá nhân, bạn có quyền:</p>
            <ul>
              <li>Được biết về hoạt động xử lý dữ liệu cá nhân của mình</li>
              <li>Truy cập, xem và yêu cầu chỉnh sửa dữ liệu cá nhân của mình</li>
              <li>Yêu cầu xuất bản sao dữ liệu của mình</li>
              <li>Yêu cầu xoá dữ liệu hoặc hạn chế xử lý dữ liệu</li>
              <li>Rút lại sự đồng ý, phản đối việc xử lý dữ liệu (ví dụ: ngắt kết nối shop, tắt cảnh báo)</li>
              <li>Từ chối nhận tiếp thị và đo lường quảng cáo, từ chối việc nêu tên shop làm ví dụ khách hàng</li>
              <li>Khiếu nại, khởi kiện và yêu cầu bồi thường theo quy định pháp luật</li>
            </ul>
            <p>
              Bạn có thể thực hiện các quyền này trong Cài đặt, mục Quyền riêng tư của ứng dụng
              (tắt tiếp thị và đo lường quảng cáo, tải dữ liệu, xoá tài khoản), hoặc gửi yêu cầu
              tới{" "}
              <a href={`mailto:${COMPANY.email}`}>
                {COMPANY.email}
              </a>
              . Chúng tôi phản hồi trong 2 ngày làm việc. Yêu cầu rút lại sự đồng ý, hạn chế
              hoặc phản đối xử lý được thực hiện trong 15 ngày; yêu cầu xem, chỉnh sửa hoặc xuất
              dữ liệu trong 10 ngày; yêu cầu xoá trong 20 ngày.
            </p>
            <p>
              Một số dữ liệu là cần thiết để Juli hoạt động (mục 6.1) hoặc là điều kiện sử dụng
              (mục 6.2). Nếu bạn rút lại sự đồng ý hoặc yêu cầu xoá những dữ liệu này, Juli
              không thể tiếp tục cung cấp dịch vụ và tài khoản của bạn được chấm dứt theo{" "}
              <a href="/terms">
                Điều khoản dịch vụ
              </a>
              . Việc rút lại sự đồng ý không ảnh hưởng đến việc xử lý đã thực hiện trước đó.
            </p>
          </LegalSection>

          <LegalSection headingId="muc-10" num="10." title="Độ tuổi sử dụng">
            <p>
              Juli là dịch vụ dành cho người bán hàng, hộ kinh doanh và doanh nghiệp dùng vào
              mục đích kinh doanh. Bạn phải từ 18 tuổi
              trở lên để sử dụng Juli. Chúng tôi không cố ý thu thập dữ liệu của người dưới
              18 tuổi.
            </p>
          </LegalSection>

          <LegalSection headingId="muc-11" num="11." title="Thay đổi chính sách này">
            <p>
              Khi chính sách thay đổi, chúng tôi cập nhật ngày ở đầu trang này và thông báo
              qua email và trong ứng dụng ít nhất 15 ngày trước khi thay đổi có hiệu lực. Việc
              tiếp tục sử dụng Juli sau thời điểm đó đồng nghĩa với việc bạn chấp nhận chính
              sách mới. Nếu Juli thay đổi cách truy cập, sử dụng, lưu trữ hoặc
              chia sẻ dữ liệu người dùng Google, chúng tôi sẽ thông báo cho bạn và xin lại sự
              đồng ý của bạn trước khi áp dụng.
            </p>
          </LegalSection>

          <LegalSection headingId="muc-12" num="12." title="Liên hệ">
            <p>
              Mọi câu hỏi về chính sách này, vui lòng liên hệ {COMPANY.name} qua{" "}
              <a href={`mailto:${COMPANY.email}`}>
                {COMPANY.email}
              </a>
              .
            </p>
          </LegalSection>

          <PrivacyPolicyEnglish />
      </LegalPage>
    </>
  );
}
