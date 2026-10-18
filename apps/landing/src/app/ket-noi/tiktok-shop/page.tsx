import {
  A,
  BLOG_PATH,
  CapabilityPage,
  CapSection,
  H3,
  Note,
  Ol,
  P,
  Ul,
} from "../../../components/product/capability-page";
import {
  CAP_KN_DANG_NHAP,
  CAP_KN_DANG_NHAP_MOBILE,
  CAP_KN_GHI,
  CAP_KN_KET_NOI,
  CAP_KN_KET_NOI_MOBILE,
  CAP_KN_QUET_NHANH,
  CAP_KN_QUET_NHANH_MOBILE,
} from "../../../components/product/screens";
import { buildMetadata } from "../../../lib/seo";
import { COMPANY } from "../../../lib/site";

/**
 * `/ket-noi/tiktok-shop` — integration page (D43.1, P33-C). Grounded in the
 * OAuth flow (SPEC §2.1, `connect-shop-view.tsx`), `/privacy` (what is read,
 * write conditions, retention), D25.13 / D25.15 (disconnect, scopes), D26 and
 * P17 (quick scan, 60-day read, history to 180 days) and D42.6 (Shopee wording).
 * Exact scope identifiers are deliberately not published (three are unverified).
 */
const PATH = "/ket-noi/tiktok-shop";

export const metadata = buildMetadata(PATH);

const FAQ = [
  {
    question: "Juli có cần mật khẩu TikTok Shop của tôi không?",
    answer:
      "Không. Bạn đăng nhập trên trang uỷ quyền của chính TikTok Shop và đồng ý cấp quyền cho ứng dụng Juli. Juli chỉ nhận mã truy cập do TikTok cấp, không bao giờ thấy mật khẩu của bạn.",
  },
  {
    question: "Kết nối mất bao lâu?",
    answer:
      "Bước uỷ quyền chỉ mất một hai phút. Sau đó Juli tự đọc dữ liệu: quét nhanh 14 ngày trong vài phút đầu, rồi đọc 60 ngày và chẩn đoán đầy đủ, thời gian tuỳ theo số sản phẩm của shop. Lịch sử cũ hơn được tải dần vào ban đêm.",
  },
  {
    question: "Juli có thay đổi gì trên shop ngay sau khi kết nối không?",
    answer:
      "Không. Kết nối chỉ cho phép Juli đọc dữ liệu và tạo đề xuất. Một thay đổi chỉ được ghi lên shop khi bạn duyệt một thẻ đề xuất và xác nhận nội dung cụ thể.",
  },
  {
    question: "Làm sao để ngắt kết nối?",
    answer:
      "Bạn liên hệ Juli qua email lienhe@app-juli.com hoặc trang Liên hệ; đội Juli ngắt kết nối shop giúp bạn. Khi đó Juli ngừng lấy dữ liệu và ngừng tạo đề xuất cho shop.",
  },
  {
    question: "Juli có hỗ trợ Shopee không?",
    answer:
      "Shopee đang được tích hợp qua Shopee Open Platform và chưa thể kết nối. Hiện Juli hoạt động với TikTok Shop.",
  },
] as const;

export default function KetNoiTikTokShopPage() {
  return (
    <CapabilityPage
      eyebrow="Kết nối"
      faq={FAQ}
      heading="Kết nối TikTok Shop với Juli: uỷ quyền chính thức, chỉ ghi khi bạn duyệt"
      ctaTitle="Kết nối shop và xem Juli đọc dữ liệu của bạn."
      heroChrome="Kết nối · Juli"
      heroCaption="Dữ liệu mẫu · tài khoản và shop minh hoạ"
      heroShot={{
        alt: "Màn hình Kết nối TikTok Shop: bạn chưa kết nối shop TikTok nào, nút Kết nối TikTok Shop (dữ liệu mẫu)",
        mobileVariants: CAP_KN_KET_NOI_MOBILE,
        variants: CAP_KN_KET_NOI,
      }}
      lead={
        <>
          Juli kết nối với TikTok Shop qua trang uỷ quyền chính thức của TikTok, như một ứng dụng của TikTok
          Shop Partner Center. Trang này giải thích bạn cấp quyền gì, Juli đọc dữ liệu nào, khi nào Juli được
          ghi lên shop, điều gì xảy ra trong giờ đầu sau khi kết nối và cách ngắt kết nối.
        </>
      }
      path={PATH}
      related={[
        {
          href: "/san-pham/phan-tich-shop",
          title: "Phân tích shop",
          body: "Dữ liệu sau khi kết nối được dùng thế nào: năm luồng truy cập và chỉ số nghẽn.",
        },
        {
          href: "/san-pham/de-xuat-va-thuc-thi",
          title: "Đề xuất và thực thi",
          body: "Juli thực hiện gì sau khi bạn duyệt, và cách hoàn tác.",
        },
        {
          href: "/privacy",
          title: "Chính sách bảo mật",
          body: "Toàn văn về dữ liệu Juli thu thập, chia sẻ, thời gian lưu và quyền của bạn.",
        },
        {
          href: BLOG_PATH,
          title: "Blog",
          body: "Hướng dẫn và kiến thức về các chỉ số TikTok Shop.",
        },
      ]}
      toc={[
        { id: "cach-ket-noi", label: "Cách kết nối" },
        { id: "doc-va-ghi", label: "Juli đọc gì, ghi gì" },
        { id: "sau-ket-noi", label: "Sau khi kết nối" },
        { id: "bao-mat", label: "Bảo mật và ngắt kết nối" },
        { id: "cau-hoi", label: "Câu hỏi thường gặp" },
      ]}
    >
      <CapSection
        alt="Màn hình Kết nối TikTok Shop trong Juli: bạn đã đăng nhập bằng một email, bạn chưa kết nối shop TikTok nào, nút Kết nối TikTok Shop và ghi chú về quyền truy cập của nhân viên Juli kèm liên kết Chính sách bảo mật"
        caption="Màn hình Kết nối TikTok Shop sau khi đăng nhập. Nút kết nối chuyển bạn sang trang uỷ quyền của TikTok."
        heading="Kết nối hoạt động thế nào"
        id="cach-ket-noi"
        image={CAP_KN_KET_NOI}
        mobileImage={CAP_KN_KET_NOI_MOBILE}
      >
        <Ol>
          <li>Đăng nhập Juli bằng Google hoặc email.</li>
          <li>
            Bấm <strong>Kết nối TikTok Shop</strong>. Juli chuyển bạn sang trang uỷ quyền của TikTok Shop.
          </li>
          <li>
            Trên trang của TikTok, bạn đăng nhập tài khoản người bán, xem danh sách quyền mà ứng dụng Juli
            yêu cầu và bấm đồng ý.
          </li>
          <li>TikTok đưa bạn trở lại Juli, và Juli bắt đầu đọc dữ liệu shop ngay.</li>
        </Ol>
        <P>
          Đường dẫn uỷ quyền được máy chủ của Juli tạo và ký cho đúng tài khoản đang đăng nhập, nên một lượt
          kết nối không thể bị gắn nhầm sang tài khoản khác. Juli không bao giờ hỏi mật khẩu shop.
        </P>
        <H3>Các nhóm quyền, nói dễ hiểu</H3>
        <P>
          Trang uỷ quyền của TikTok liệt kê chính xác từng quyền. Juli dùng các quyền đó cho những việc sau:
        </P>
        <Ul>
          <li>Xem thông tin shop và danh sách sản phẩm.</li>
          <li>Xem đơn hàng, chi tiết giá của đơn và giao dịch tài chính theo đơn.</li>
          <li>Xem số liệu phân tích của shop, sản phẩm, video và LIVE.</li>
          <li>Xem khuyến mãi và voucher đang chạy.</li>
          <li>Cập nhật thông tin sản phẩm, chỉ khi bạn đã duyệt và xác nhận một thay đổi cụ thể.</li>
        </Ul>
        <H3>Khi thiếu quyền</H3>
        <P>
          Mỗi lần làm mới mã truy cập, Juli ghi lại những quyền TikTok thực sự đã cấp. Nếu Juli cần một quyền
          mà shop chưa cấp, ứng dụng hiện dòng “Kết nối lại TikTok Shop để cấp quyền mới”, và bạn chỉ cần đi
          lại bước uỷ quyền.
        </P>
      </CapSection>

      <CapSection
        alt="Thẻ đề xuất Son môi số 12 sau khi bấm Duyệt: trạng thái Đang thực hiện, thông báo Juli đã tạo lượt chạy, đọc chẩn đoán TikTok và soạn nội dung, bạn xác nhận lần cuối trước khi Juli ghi lên TikTok Shop"
        caption="Sau khi bấm Duyệt: Juli chuẩn bị nội dung, nhưng chỉ ghi lên TikTok Shop sau khi bạn xác nhận lần cuối."
        heading="Juli đọc gì và ghi gì trên shop"
        id="doc-va-ghi"
        image={CAP_KN_GHI}
        narrow
      >
        <H3>Dữ liệu Juli đọc</H3>
        <P>
          Sau khi kết nối, Juli đồng bộ định kỳ các dữ liệu sau từ API của TikTok Shop, theo{" "}
          <A href="/privacy">Chính sách bảo mật</A>:
        </P>
        <Ul>
          <li>Đơn hàng và chi tiết đơn (mã đơn, trạng thái, giá trị, thời gian thanh toán và giao hàng).</li>
          <li>Sản phẩm (tên, danh mục, giá bán, doanh thu, số lượng đã bán) và tồn kho theo SKU.</li>
          <li>Đơn hoàn và huỷ (loại, lý do, số tiền hoàn).</li>
          <li>Số liệu hiệu suất theo từng luồng truy cập, và hiệu suất video, LIVE của shop.</li>
          <li>Chương trình khuyến mãi và mã giảm giá của shop.</li>
        </Ul>
        <P>
          Juli không đọc tin nhắn của bạn, và không lưu thông tin liên hệ của người mua ngoài mã định danh cần
          thiết để xử lý đơn hàng.
        </P>
        <H3>Những gì Juli được ghi</H3>
        <P>
          Một thao tác trên shop chỉ xảy ra khi bạn đã duyệt đề xuất đó và xác nhận nội dung, với quyền ghi
          cấp riêng cho đúng một sản phẩm và một loại thao tác, có thời hạn và chỉ dùng một lần. Những thay
          đổi Juli thực hiện là tiêu đề và mô tả sản phẩm, và ảnh bìa khi bạn cung cấp ảnh. Mọi thay đổi đều
          được lưu giá trị cũ để hoàn tác.
        </P>
        <H3>Những gì Juli không ghi</H3>
        <Ul>
          <li>Giá sản phẩm: Juli chỉ đề xuất.</li>
          <li>Khuyến mãi và voucher: bạn tạo trên Seller Center theo hướng dẫn của Juli.</li>
          <li>Không có gì khác ngoài những thay đổi bạn đã duyệt và xác nhận.</li>
        </Ul>
      </CapSection>

      <CapSection
        alt="Dải tiến trình Juli đang đọc dữ liệu shop bước 2 trên 3: bước 1 Quét nhanh 14 ngày đã xong, bước 2 Đọc 60 ngày và chẩn đoán đầy đủ đang chạy 43 % còn khoảng 9 phút, bước 3 Tải lịch sử nền đang chờ"
        caption="Dải tiến trình hiện ở Trang chủ, Quyết định và Phân tích trong lúc Juli đọc một shop vừa kết nối."
        heading="Sau khi kết nối: quét nhanh, rồi đọc đầy đủ"
        id="sau-ket-noi"
        image={CAP_KN_QUET_NHANH}
        mobileImage={CAP_KN_QUET_NHANH_MOBILE}
      >
        <P>
          Bạn không cần bấm gì thêm. Ngay khi TikTok đưa bạn trở lại, Juli chạy ba bước và hiện tiến trình
          “Juli đang đọc dữ liệu shop · bước 1/3” trên các màn hình chính:
        </P>
        <Ol>
          <li>
            <strong>Quét nhanh 14 ngày.</strong> Trong vài phút, Juli đọc hiệu suất sản phẩm 14 ngày gần nhất
            và chẩn đoán sản phẩm của TikTok cho các sản phẩm bán chạy, rồi có thể đưa ra vài đề xuất nhanh
            về ảnh bìa, tiêu đề hoặc mô tả, ghi “Đề xuất nhanh · dựa trên 14 ngày”.
          </li>
          <li>
            <strong>Đọc 60 ngày và chẩn đoán đầy đủ.</strong> Juli đọc 60 ngày đơn hàng và số liệu phân tích,
            dựng báo cáo Phân tích và các thẻ đề xuất đầy đủ. Thời gian tuỳ theo số sản phẩm; dải tiến trình
            ghi phần trăm và thời gian ước tính còn lại.
          </li>
          <li>
            <strong>Tải lịch sử nền.</strong> Mỗi đêm Juli tải thêm lịch sử cũ hơn, đến 180 ngày hoặc đến giới
            hạn TikTok cho phép, ở mức ưu tiên thấp để không làm chậm phần còn lại.
          </li>
        </Ol>
        <H3>Sau đó, mỗi ngày</H3>
        <P>
          Đơn hàng, sản phẩm và tồn kho được đồng bộ nhiều lần trong ngày; số liệu phân tích được lấy mỗi
          ngày khi TikTok công bố ngày mới, và báo cáo được dựng lại. Chi tiết ở trang{" "}
          <A href="/san-pham/phan-tich-shop">Phân tích shop</A>.
        </P>
      </CapSection>

      <CapSection
        alt="Màn hình bắt đầu của Juli: lựa chọn Dùng thử Demo không cần tài khoản, hoặc đăng nhập tài khoản thật bằng Google hoặc email, kèm dòng đồng ý với Điều khoản dịch vụ và Chính sách bảo mật"
        caption="Màn hình bắt đầu: xem bản demo với dữ liệu mẫu, hoặc đăng nhập để kết nối shop thật."
        heading="Bảo mật và ngắt kết nối"
        id="bao-mat"
        image={CAP_KN_DANG_NHAP}
        mobileImage={CAP_KN_DANG_NHAP_MOBILE}
      >
        <H3>Mã truy cập được mã hoá</H3>
        <P>
          Mã truy cập TikTok Shop của bạn được mã hoá trước khi lưu, và khoá giải mã nằm trong hệ thống quản
          lý khoá bí mật, không nằm trong mã nguồn. Mã được làm mới tự động trước khi hết hạn.
        </P>
        <H3>Ai được xem dữ liệu shop</H3>
        <P>
          Dữ liệu shop chỉ dùng để cung cấp dịch vụ cho chính bạn. Khi kết nối, bạn đồng ý để nhân viên Juli
          xem dữ liệu shop nhằm hỗ trợ và vận hành dịch vụ; nhân viên không bao giờ xem dữ liệu người mua, và
          mọi lần truy cập đều được ghi nhật ký. Dữ liệu gửi đến OpenAI để soạn nội dung không được dùng để
          huấn luyện mô hình.
        </P>
        <H3>Ngắt kết nối</H3>
        <P>
          Bạn liên hệ Juli qua email{" "}
          <A href={`mailto:${COMPANY.email}`}>{COMPANY.email}</A> hoặc{" "}
          <A href="/contact">trang Liên hệ</A>; đội Juli ngắt kết nối shop giúp bạn. Juli ngừng lấy dữ
          liệu mới và ngừng tạo đề xuất cho shop đó ngay. Lịch
          sử, quy tắc và kết quả đo được giữ lại để bạn kết nối lại khi cần; nếu bạn yêu cầu xoá tài khoản,
          dữ liệu tài khoản và dữ liệu shop được xoá trong vòng 30 ngày, trừ dữ liệu pháp luật yêu cầu lưu.
        </P>
        <H3>Shopee: đang tích hợp</H3>
        <P>
          Shopee đang được tích hợp qua Shopee Open Platform và chưa thể kết nối. Khi tích hợp hoàn tất, trang
          này và Chính sách bảo mật sẽ mô tả cách kết nối và dữ liệu Juli đọc.
        </P>
        <Note>
          Ảnh trên trang này lấy từ ứng dụng Juli với tài khoản và shop minh hoạ. Tên shop, email và số liệu
          là dữ liệu mẫu.
        </Note>
      </CapSection>
    </CapabilityPage>
  );
}
