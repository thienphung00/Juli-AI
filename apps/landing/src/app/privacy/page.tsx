import type { Metadata } from "next";

import { LandingHeader } from "../../components/landing-header";
import { SiteFooter } from "../../components/site-footer";
import { COMPANY } from "../../lib/site";
import {
  ENGLISH_SECTION_ID,
  GOOGLE_PERMISSIONS_URL,
  GOOGLE_USER_DATA_POLICY_URL,
  LAST_UPDATED_EN,
  PrivacyPolicyEnglish,
  VERSION_EN,
} from "./privacy-policy-english";

export const metadata: Metadata = {
  title: "Chính sách bảo mật / Privacy Policy — Juli AI",
  description:
    "Juli AI thu thập gì, đọc gì từ shop TikTok Shop và Shopee của bạn, chia sẻ với ai, lưu trong bao lâu, và quyền của bạn với dữ liệu đó. Full English version included: what data Juli AI collects (including Google user data), how it is used, shared, protected, retained and deleted.",
};

const VERSION = "2.0";
const LAST_UPDATED = "14/10/2026";

/** Anchor for §3, so the Google OAuth consent screen can deep-link to it. */
const GOOGLE_SECTION_ID = "du-lieu-nguoi-dung-google";

export default function PrivacyPolicyPage() {
  return (
    <>
      <LandingHeader />
      <main className="lp-main">
        <article className="lp-legal">
          <p className="lp-legal__eyebrow">Pháp lý</p>
          <h1 className="lp-legal__heading">Chính sách bảo mật</h1>
          <p className="lp-legal__updated">
            Phiên bản: {VERSION} — Cập nhật lần cuối: {LAST_UPDATED}
          </p>

          <div className="lp-legal__en-notice" lang="en" data-testid="privacy-en-notice">
            <p>
              <strong>Privacy Policy — Juli AI.</strong> App name: Juli AI. Operator:{" "}
              <span lang="vi">{COMPANY.name}</span> (tax ID {COMPANY.taxId}). Website:
              app-juli.com. Contact:{" "}
              <a className="lp-legal__contact-link" href={`mailto:${COMPANY.email}`}>
                {COMPANY.email}
              </a>
              . Version: {VERSION_EN}. Last updated (effective date): {LAST_UPDATED_EN}.
            </p>
            <p>
              <a className="lp-legal__contact-link" href={`#${ENGLISH_SECTION_ID}`}>
                English version ↓
              </a>
            </p>
          </div>

          <p className="lp-legal__intro">
            Chính sách này giải thích cách Juli AI thu thập, sử dụng, chia sẻ và bảo vệ dữ
            liệu khi bạn sử dụng website app-juli.com, bản Demo và ứng dụng Juli, phù hợp
            với Luật Bảo vệ dữ liệu cá nhân và các văn bản hướng dẫn thi hành.
          </p>
          <p className="lp-legal__intro">
            Trang này có bản tiếng Anh đầy đủ ở phía dưới. Nếu hai bản có khác biệt, bản
            tiếng Việt được ưu tiên áp dụng, trừ trường hợp điều đó mâu thuẫn với các cam
            kết của Juli AI theo Chính sách dữ liệu người dùng của Google API Services, bao
            gồm các yêu cầu Sử dụng giới hạn (Limited Use) tại mục 3 — các cam kết này luôn
            được áp dụng.
          </p>

          <section className="lp-legal__section">
            <h2 className="lp-legal__section-heading">1. Chúng tôi là ai</h2>
            <p>
              Juli AI được vận hành bởi {COMPANY.name} (mã số thuế {COMPANY.taxId}), trụ sở
              tại {COMPANY.address}. {COMPANY.name} là bên kiểm soát và xử lý dữ liệu cá
              nhân được mô tả trong chính sách này. Riêng đối với dữ liệu cá nhân của người
              mua có trong dữ liệu shop, người bán là bên kiểm soát dữ liệu và Juli xử lý dữ
              liệu đó thay mặt người bán, theo mục 10 của{" "}
              <a className="lp-legal__contact-link" href="/terms">
                Điều khoản dịch vụ
              </a>
              .
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
              <li>
                Thông tin xuất hoá đơn: tên doanh nghiệp/hộ kinh doanh hoặc họ tên, mã số
                thuế hoặc số định danh cá nhân, địa chỉ, email nhận hoá đơn — chỉ khi bạn
                thanh toán
              </li>
            </ul>
          </section>

          <section
            className="lp-legal__section"
            id={GOOGLE_SECTION_ID}
            aria-labelledby="google-user-data-heading"
          >
            <h2 className="lp-legal__section-heading" id="google-user-data-heading">
              3. Dữ liệu người dùng Google (Google user data)
            </h2>
            <p>
              Mục này áp dụng khi bạn chọn &ldquo;Đăng nhập với Google&rdquo; trên Juli AI
              (app-juli.com và demo.app-juli.com), do {COMPANY.name} vận hành. Việc đăng
              nhập được thực hiện qua Supabase Auth. Juli chỉ yêu cầu các quyền đăng nhập cơ
              bản của Google: <strong>openid</strong>, <strong>email</strong> và{" "}
              <strong>profile</strong>. Juli không yêu cầu quyền truy cập Gmail, Google
              Drive, Danh bạ, Lịch hay bất kỳ dịch vụ hoặc dữ liệu Google nào khác.
            </p>

            <h3 className="lp-legal__subheading">3.1. Dữ liệu Juli truy cập</h3>
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

            <h3 className="lp-legal__subheading">3.2. Cách Juli sử dụng dữ liệu này</h3>
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
              cầu. Nhân viên chỉ xem dữ liệu shop cần thiết cho việc hỗ trợ, không sao chép hay
              lưu trữ dữ liệu người mua, và mọi lần truy cập đều được ghi nhật ký.
            </p>
            <p>
              Việc Juli sử dụng và chuyển cho bất kỳ ứng dụng nào khác thông tin nhận được từ
              Google API tuân thủ{" "}
              <a
                className="lp-legal__contact-link"
                href={GOOGLE_USER_DATA_POLICY_URL}
                rel="noopener noreferrer"
                target="_blank"
              >
                Chính sách dữ liệu người dùng của Google API Services (Google API Services
                User Data Policy)
              </a>
              , bao gồm các yêu cầu về Sử dụng giới hạn (Limited Use).
            </p>

            <h3 className="lp-legal__subheading">3.3. Juli chia sẻ dữ liệu này với ai</h3>
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

            <h3 className="lp-legal__subheading">3.4. Cách Juli bảo vệ dữ liệu này</h3>
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

            <h3 className="lp-legal__subheading">3.5. Lưu trữ, xoá dữ liệu và thu hồi quyền truy cập</h3>
            <ul aria-label="Lưu trữ và xoá dữ liệu người dùng Google">
              <li>
                Lưu trữ: Juli giữ dữ liệu người dùng Google nêu ở mục 3.1 trong thời gian tài
                khoản Juli của bạn còn tồn tại
              </li>
              <li>
                Yêu cầu xoá: gửi email tới{" "}
                <a className="lp-legal__contact-link" href={`mailto:${COMPANY.email}`}>
                  {COMPANY.email}
                </a>{" "}
                từ địa chỉ email của tài khoản. Chúng tôi xác nhận trong vòng 72 giờ và xoá tài
                khoản cùng toàn bộ dữ liệu người dùng Google khỏi hệ thống của Juli và Supabase
                trong vòng 30 ngày kể từ khi nhận yêu cầu
              </li>
              <li>
                Thu hồi quyền truy cập: bạn có thể gỡ quyền truy cập của Juli bất kỳ lúc nào tại{" "}
                <a
                  className="lp-legal__contact-link"
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
          </section>

          <section className="lp-legal__section">
            <h2 className="lp-legal__section-heading">
              4. Thông tin chúng tôi đọc từ shop của bạn
            </h2>
            <p>
              Juli hỗ trợ shop trên TikTok Shop và Shopee. Juli truy cập dữ liệu shop theo
              một trong hai cách, tuỳ sàn và tuỳ lựa chọn của bạn:
            </p>
            <ul aria-label="Cách Juli truy cập dữ liệu shop">
              <li>
                (a) Kết nối ủy quyền chính thức qua API của sàn: bạn bấm đường dẫn ủy quyền,
                sàn hiển thị danh sách quyền Juli yêu cầu và bạn chấp thuận. Áp dụng cho
                TikTok Shop, và cho Shopee sau khi ứng dụng của Juli được Shopee cấp phép.
              </li>
              <li>
                (b) Tài khoản phụ do bạn cấp: bạn tạo một tài khoản phụ trong Kênh Người Bán
                của sàn (ví dụ: Shopee), tự chọn phạm vi quyền của tài khoản đó và cấp cho
                Juli. Bạn có thể đổi mật khẩu, thu hẹp quyền hoặc khoá tài khoản phụ bất kỳ
                lúc nào. Juli bảo mật thông tin đăng nhập của tài khoản phụ, chỉ dùng tài
                khoản này để phục vụ shop của bạn và không chia sẻ cho bên thứ ba.
              </li>
            </ul>
            <p>
              Juli định kỳ đọc các dữ liệu sau, dùng để phân tích và đưa ra đề xuất cho shop
              của bạn:
            </p>
            <ul aria-label="Dữ liệu shop Juli đọc">
              <li>Đơn hàng và chi tiết từng đơn hàng (mã đơn, trạng thái, giá trị, thời gian thanh toán/giao hàng)</li>
              <li>Sản phẩm (tên, danh mục, giá bán, doanh thu, số lượng đã bán)</li>
              <li>Tồn kho theo từng sản phẩm/SKU và kho hàng</li>
              <li>Đơn hoàn/hủy (loại hoàn, lý do, số tiền hoàn)</li>
              <li>Số liệu hiệu suất shop do sàn cung cấp (doanh thu, lượt xem, tỷ lệ chuyển đổi theo từng luồng truy cập)</li>
              <li>Hiệu suất video và LIVE của shop, cùng các sản phẩm được gắn trong đó</li>
              <li>Chương trình khuyến mãi, mã giảm giá và số liệu quảng cáo của shop</li>
            </ul>
            <p>
              Juli không đọc tin nhắn cá nhân của bạn, và không thu thập hay lưu trữ thông
              tin liên hệ của người mua (tên, số điện thoại, địa chỉ) ngoài mã định danh cần
              thiết để xử lý đơn hàng — kể cả khi các thông tin này hiển thị trong Kênh Người
              Bán mà tài khoản phụ có quyền xem.
            </p>
          </section>

          <section className="lp-legal__section">
            <h2 className="lp-legal__section-heading">
              5. Những gì Juli ghi lại hoặc thay đổi trên shop của bạn
            </h2>
            <p>
              Mặc định, Juli chỉ đọc dữ liệu và không thay đổi bất kỳ điều gì trên shop thật
              của bạn. Việc thử nghiệm các hành động (ví dụ: tạo mã giảm giá sản phẩm) chạy
              trên môi trường thử nghiệm (sandbox) do sàn cung cấp, khi có, tách biệt khỏi
              shop thật.
            </p>
            <p>
              Một thao tác trên shop thật chỉ được thực hiện khi (a) bạn đã chủ động phê
              duyệt đề xuất đó, và (b) thao tác được giới hạn đúng sản phẩm và đúng loại
              thao tác bạn đã phê duyệt. Với kết nối API, mỗi thao tác dùng một quyền ghi
              riêng, có thời hạn và chỉ dùng được một lần. Với tài khoản phụ, Juli chỉ thực
              hiện đúng thao tác bạn đã phê duyệt, trong phạm vi quyền bạn đã cấp cho tài
              khoản đó.
            </p>
          </section>

          <section className="lp-legal__section">
            <h2 className="lp-legal__section-heading">6. Mục đích sử dụng dữ liệu</h2>
            <ul>
              <li>Cung cấp, vận hành và bảo mật tài khoản và dịch vụ Juli</li>
              <li>Phân tích hiệu suất shop và tạo đề xuất tối ưu cho shop của bạn</li>
              <li>Gửi cảnh báo và thông báo mà bạn đã bật</li>
              <li>Đo lường hiệu quả quảng cáo của Juli trên TikTok</li>
              <li>Liên hệ hỗ trợ và thông báo các thay đổi quan trọng về dịch vụ</li>
              <li>
                Xuất hoá đơn, lưu chứng từ thanh toán và thực hiện nghĩa vụ kế toán, thuế
                theo quy định pháp luật
              </li>
              <li>
                Tối ưu thuật toán phân tích và chất lượng gợi ý của Juli, bao gồm tinh chỉnh
                (fine-tune) mô hình ngôn ngữ, chỉ với dữ liệu đã ẩn danh hoá ở dạng cấu trúc
                (xem bên dưới)
              </li>
            </ul>
            <p>
              Với mục đích tối ưu thuật toán, Juli chỉ sử dụng dữ liệu shop đã được ẩn danh
              hoá, chỉ ở dạng cấu trúc dữ liệu (ví dụ: loại chỉ số, mối tương quan giữa các
              chỉ số, loại đề xuất và kết quả sau khi áp dụng). Dữ liệu này không chứa tên
              shop, tên hoặc nội dung sản phẩm, hình ảnh, kịch bản, tiêu đề, số liệu kinh
              doanh có thể nhận diện shop, thông tin người mua hay dữ liệu người dùng Google,
              và không được tiết lộ cho khách hàng khác. Bạn có thể yêu cầu ngừng sử dụng dữ
              liệu của mình cho mục đích này bất kỳ lúc nào qua email{" "}
              <a className="lp-legal__contact-link" href={`mailto:${COMPANY.email}`}>
                {COMPANY.email}
              </a>
              .
            </p>
            <p>
              Gợi ý kịch bản, tiêu đề và nội dung được xử lý riêng cho từng shop, dựa trên dữ
              liệu và cách dùng từ ngữ của chính shop đó; nội dung riêng của shop chỉ dùng để
              tạo gợi ý cho chính shop đó.
            </p>
          </section>

          <section className="lp-legal__section">
            <h2 className="lp-legal__section-heading">7. Chúng tôi chia sẻ dữ liệu với ai</h2>
            <p>
              Juli không bán, không tiết lộ và không chuyển giao dữ liệu của bạn cho bất kỳ
              bên thứ ba nào, và không sử dụng dữ liệu của bạn sai mục đích (bao gồm không
              dùng dữ liệu có thể nhận diện shop của bạn để phục vụ khách hàng khác). Chúng
              tôi chỉ chia sẻ dữ liệu với các bên xử lý dữ liệu sau, trong phạm vi cần thiết
              để vận hành sản phẩm:
            </p>
            <ul aria-label="Bên xử lý dữ liệu">
              <li>Supabase — xác thực đăng nhập (Google) và lưu trữ cơ sở dữ liệu</li>
              <li>
                TikTok Shop API và Shopee (API hoặc Kênh Người Bán) — nguồn dữ liệu shop của
                bạn
              </li>
              <li>
                OpenAI — mô hình ngôn ngữ (AI) do bên thứ ba cung cấp, dùng để phân tích dữ
                liệu shop và tạo đề xuất. Juli chỉ gửi cho OpenAI thông tin gian hàng mà nền
                tảng (TikTok Shop, Shopee) đã cấp quyền truy cập, ở mức cần thiết cho từng
                phân tích; không gửi thông tin liên hệ của người mua và không gửi dữ liệu
                người dùng Google. Dữ liệu gửi qua API của OpenAI không được OpenAI dùng để
                huấn luyện các mô hình chung của OpenAI và chỉ được lưu tạm thời theo chính
                sách dữ liệu API của OpenAI; mô hình tinh chỉnh (nếu có) là mô hình riêng của
                Juli và chỉ dùng dữ liệu đã ẩn danh hoá theo mục 6. Juli giới hạn phạm vi và
                mức sử dụng mô hình cho từng tài khoản
              </li>
              <li>Nhà cung cấp máy chủ (VPS) — nơi chạy ứng dụng Juli</li>
              <li>Amazon Web Services (AWS) — quản lý khoá bí mật của hệ thống</li>
              <li>Zalo (Zalo OA) và Google Firebase — gửi cảnh báo và thông báo đẩy mà bạn đã bật</li>
              <li>
                Viettel-CA — xuất, gửi và lưu trữ hoá đơn điện tử, và chuyển dữ liệu hoá đơn
                tới cơ quan thuế theo quy định
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
              Một số bên xử lý trên đặt máy chủ ngoài Việt Nam (ví dụ: Hoa Kỳ), nên dữ liệu
              có thể được chuyển ra nước ngoài. Chúng tôi chỉ chuyển dữ liệu cần thiết cho
              mục đích nêu tại mục 6. Chúng tôi cũng có thể cung cấp dữ liệu khi cơ quan nhà
              nước có thẩm quyền yêu cầu theo quy định pháp luật.
            </p>
          </section>

          <section className="lp-legal__section">
            <h2 className="lp-legal__section-heading">8. Bảo mật và thời gian lưu trữ</h2>
            <p>
              Dữ liệu được mã hoá khi truyền (HTTPS/TLS) và được nhà cung cấp cơ sở dữ liệu
              (Supabase) mã hoá khi lưu trữ. Quyền truy cập dữ liệu được giới hạn theo từng
              tài khoản và từng shop. Khoá truy cập của sàn và thông tin đăng nhập tài khoản
              phụ được lưu trong hệ thống quản lý khoá bí mật, không lưu trong mã nguồn. Chi
              tiết riêng cho dữ liệu người dùng Google nằm ở mục 3.4 và 3.5.
            </p>
            <p>
              Juli tuân thủ nghiêm ngặt các chính sách về truy cập, xử lý và bảo vệ dữ liệu
              của TikTok Shop và Shopee: chỉ truy cập dữ liệu trong phạm vi quyền bạn đã cấp
              và cần thiết cho việc phân tích, và không lưu trữ dữ liệu ngoài hệ thống của
              Juli.
            </p>
            <p>
              Chúng tôi lưu dữ liệu trong thời gian bạn sử dụng Juli. Khi bạn ngắt kết nối
              shop hoặc khoá tài khoản phụ, Juli ngừng đồng bộ dữ liệu mới từ shop đó ngay
              lập tức, và xoá dữ liệu shop đã đồng bộ trong vòng 30 ngày. Khi bạn yêu cầu xoá
              tài khoản, dữ liệu tài khoản và dữ liệu shop được xoá trong vòng 30 ngày, trừ
              những dữ liệu pháp luật yêu cầu phải lưu giữ: hoá đơn, chứng từ thanh toán và
              thông tin xuất hoá đơn được lưu trong thời hạn theo pháp luật về kế toán (tối
              thiểu 10 năm).
            </p>
          </section>

          <section className="lp-legal__section">
            <h2 className="lp-legal__section-heading">9. Quyền của bạn</h2>
            <p>Theo pháp luật về bảo vệ dữ liệu cá nhân, bạn có quyền:</p>
            <ul>
              <li>Được biết và truy cập dữ liệu cá nhân của mình</li>
              <li>Yêu cầu chỉnh sửa dữ liệu không chính xác</li>
              <li>Yêu cầu xuất bản sao dữ liệu của mình</li>
              <li>Yêu cầu xoá dữ liệu hoặc hạn chế xử lý dữ liệu</li>
              <li>
                Rút lại sự đồng ý bất kỳ lúc nào (ví dụ: ngắt kết nối shop, khoá tài khoản
                phụ, tắt cảnh báo)
              </li>
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
            <h2 className="lp-legal__section-heading">10. Độ tuổi sử dụng</h2>
            <p>
              Juli là dịch vụ dành cho người bán hàng và doanh nghiệp. Bạn phải từ 18 tuổi
              trở lên để sử dụng Juli. Chúng tôi không cố ý thu thập dữ liệu của người dưới
              18 tuổi.
            </p>
          </section>

          <section className="lp-legal__section">
            <h2 className="lp-legal__section-heading">11. Thay đổi chính sách này</h2>
            <p>
              Khi chính sách thay đổi, chúng tôi cập nhật số phiên bản và ngày ở đầu trang
              này. Với những
              thay đổi quan trọng, chúng tôi thông báo qua email ít nhất 7 ngày trước khi
              thay đổi có hiệu lực. Nếu Juli thay đổi cách truy cập, sử dụng, lưu trữ hoặc
              chia sẻ dữ liệu người dùng Google, chúng tôi sẽ thông báo cho bạn và xin lại sự
              đồng ý của bạn trước khi áp dụng.
            </p>
          </section>

          <section className="lp-legal__section">
            <h2 className="lp-legal__section-heading">12. Liên hệ</h2>
            <p>
              Mọi câu hỏi về chính sách này, vui lòng liên hệ {COMPANY.name} qua{" "}
              <a className="lp-legal__contact-link" href={`mailto:${COMPANY.email}`}>
                {COMPANY.email}
              </a>
              .
            </p>
          </section>

          <PrivacyPolicyEnglish />
        </article>
      </main>
      <SiteFooter />
    </>
  );
}
