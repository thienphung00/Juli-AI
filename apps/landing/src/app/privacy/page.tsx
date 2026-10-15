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

const LAST_UPDATED = "15/10/2026";

/** Anchor for the trial sign-up paragraph in §2 (P33-F), linked from /dang-ky's consent. */
const TRIAL_SIGNUP_SECTION_ID = "dang-ky-dung-thu";

/** Anchor for §3, so the Google OAuth consent screen can deep-link to it. */
const GOOGLE_SECTION_ID = "du-lieu-nguoi-dung-google";

/**
 * "Tóm tắt dễ hiểu" (D44): each line restates what a numbered section below
 * already says (§4, §5, §3 + staff access, §3.2/§7, §9 + §8). It adds no
 * commitment; the full text governs.
 */
const SUMMARY = [
  "Sau khi bạn kết nối shop, Juli đọc dữ liệu shop (đơn hàng, sản phẩm, tồn kho, đơn hoàn, hiệu suất) qua API của TikTok Shop để phân tích và đề xuất cho shop của bạn.",
  "Mặc định Juli không thay đổi gì trên shop thật; một thao tác chỉ được thực hiện sau khi bạn đã duyệt đề xuất đó.",
  "Nhân viên Juli chỉ xem dữ liệu shop để hỗ trợ và vận hành dịch vụ, không xem dữ liệu người mua, và mọi lần truy cập đều được ghi nhật ký.",
  "Juli không bán dữ liệu, và không dùng dữ liệu người dùng Google cho quảng cáo hay để huấn luyện các mô hình AI tổng quát.",
  "Để ngắt kết nối shop hoặc xoá tài khoản, bạn gửi email cho Juli; dữ liệu tài khoản và dữ liệu shop được xoá trong vòng 30 ngày, trừ dữ liệu pháp luật yêu cầu lưu giữ.",
] as const;

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
        summary={SUMMARY}
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
            với Nghị định 13/2023/NĐ-CP về bảo vệ dữ liệu cá nhân.
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
              nhân được mô tả trong chính sách này.
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
              ; chúng tôi xoá trong vòng 30 ngày.
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
                từ địa chỉ email của tài khoản. Chúng tôi xác nhận trong vòng 72 giờ và xoá tài
                khoản cùng toàn bộ dữ liệu người dùng Google khỏi hệ thống của Juli và Supabase
                trong vòng 30 ngày kể từ khi nhận yêu cầu
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
              ngắt kết nối shop, và xoá trong vòng 30 ngày kể từ khi bạn yêu cầu xoá tài
              khoản. Juli tuân thủ Chính sách bảo vệ dữ liệu (Data Protection Policy) của
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
            <ul>
              <li>Cung cấp, vận hành và bảo mật tài khoản và dịch vụ Juli</li>
              <li>Phân tích hiệu suất shop và tạo đề xuất tối ưu cho shop của bạn</li>
              <li>Gửi cảnh báo và thông báo mà bạn đã bật</li>
              <li>Đo lường hiệu quả quảng cáo của Juli trên TikTok</li>
              <li>Liên hệ hỗ trợ và thông báo các thay đổi quan trọng về dịch vụ</li>
            </ul>
          </LegalSection>

          <LegalSection headingId="muc-7" num="7." title="Chúng tôi chia sẻ dữ liệu với ai">
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
                TikTok chỉ nhận mã người dùng Juli đã được băm (SHA-256) — không nhận email
                hay bất kỳ dữ liệu người dùng Google nào
              </li>
            </ul>
            <p>
              Một số bên xử lý trên đặt máy chủ ngoài Việt Nam (ví dụ: Hoa Kỳ), nên dữ liệu
              có thể được chuyển ra nước ngoài. Chúng tôi chỉ chuyển dữ liệu cần thiết cho
              mục đích nêu tại mục 6. Chúng tôi cũng có thể cung cấp dữ liệu khi cơ quan nhà
              nước có thẩm quyền yêu cầu theo quy định pháp luật.
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
              Chúng tôi lưu dữ liệu trong thời gian bạn sử dụng Juli. Khi bạn ngắt kết nối
              shop, Juli ngừng đồng bộ dữ liệu mới từ shop đó ngay lập tức. Khi bạn yêu cầu
              xoá tài khoản, dữ liệu tài khoản và dữ liệu shop được xoá trong vòng 30 ngày,
              trừ những dữ liệu pháp luật yêu cầu phải lưu giữ (ví dụ: chứng từ thanh toán).
            </p>
          </LegalSection>

          <LegalSection headingId="muc-9" num="9." title="Quyền của bạn">
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
              <a href={`mailto:${COMPANY.email}`}>
                {COMPANY.email}
              </a>
              . Chúng tôi phản hồi trong vòng 72 giờ.
            </p>
          </LegalSection>

          <LegalSection headingId="muc-10" num="10." title="Độ tuổi sử dụng">
            <p>
              Juli là dịch vụ dành cho người bán hàng và doanh nghiệp. Bạn phải từ 18 tuổi
              trở lên để sử dụng Juli. Chúng tôi không cố ý thu thập dữ liệu của người dưới
              18 tuổi.
            </p>
          </LegalSection>

          <LegalSection headingId="muc-11" num="11." title="Thay đổi chính sách này">
            <p>
              Khi chính sách thay đổi, chúng tôi cập nhật ngày ở đầu trang này. Với những
              thay đổi quan trọng, chúng tôi thông báo qua email ít nhất 7 ngày trước khi
              thay đổi có hiệu lực. Nếu Juli thay đổi cách truy cập, sử dụng, lưu trữ hoặc
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
