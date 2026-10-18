import {
  A,
  BLOG_PATH,
  CapabilityPage,
  CapSection,
  H3,
  Note,
  P,
  Ul,
} from "../../../components/product/capability-page";
import { StreamGrid } from "../../../components/product/diagrams";
import {
  CAP_PT_KHUYEN_MAI,
  CAP_PT_KHUYEN_MAI_MOBILE,
  CAP_PT_LICH_SALE,
  CAP_PT_LICH_SALE_MOBILE,
  CAP_PT_LUONG,
  CAP_PT_LUONG_MOBILE,
  CAP_PT_NGHEN,
  CAP_PT_NGHEN_MOBILE,
  CAP_PT_PHEU,
  CAP_PT_PHEU_MOBILE,
  CAP_PT_XEP_HANG,
  CAP_PT_XEP_HANG_MOBILE,
} from "../../../components/product/screens";
import { FunnelDiagram } from "../../../components/ui";
import { buildMetadata } from "../../../lib/seo";
import { FREE_TOOLS } from "../../../lib/site";

/**
 * `/san-pham/phan-tich-shop` — capability page "Phân tích" (D43.1, D43.4, P33-C).
 * Grounded in ADR-108 (five channels, per-channel funnel, decomposition,
 * confidence labels), ADR-106 / D22 (GMV identity) and the demo's Phân tích.
 */
const PATH = "/san-pham/phan-tich-shop";

export const metadata = buildMetadata(PATH);

const FAQ = [
  {
    question: "Vì sao shop TikTok không ra đơn?",
    answer:
      "Thường là vì một bước trong phễu đang nghẽn, và mỗi bước có nguyên nhân khác nhau. Lượt hiển thị thấp: ít người mua thấy sản phẩm. CTR thấp: người mua thấy nhưng không bấm, thường do ảnh bìa, tiêu đề hoặc giá hiển thị. CTOR thấp: người mua bấm vào nhưng không đặt hàng, do giá, mô tả, đánh giá, voucher hay phí vận chuyển. Khi đã có đơn mà GMV vẫn thấp, hãy xem AOV. Juli đọc bốn chỉ số này theo từng luồng truy cập và từng sản phẩm, so với mức dao động bình thường của chính shop, để chỉ ra bước cần sửa trước.",
  },
  {
    question: "Juli lấy số liệu phân tích từ đâu?",
    answer:
      "Từ chính TikTok Shop của bạn, qua API chính thức mà bạn uỷ quyền khi kết nối: số liệu hiệu suất sản phẩm theo từng kênh, đơn hàng, sản phẩm, video, LIVE và khuyến mãi. Juli không cào dữ liệu từ trang web và không dùng số liệu ước đoán của bên thứ ba cho phần Phân tích.",
  },
  {
    question: "Số trên Juli có khớp với Trung tâm nhà bán hàng không?",
    answer:
      "Juli dùng đúng định nghĩa của TikTok: CTR = lượt nhấp ÷ lượt hiển thị, CTOR = đơn hàng SKU ÷ lượt nhấp, AOV (SKU) = GMV ÷ đơn hàng SKU, và GMV gồm cả đơn đã huỷ và hoàn tiền. Tỷ lệ của cả kỳ được tính từ tổng của kỳ, giống Seller Center. Khác biệt nhỏ vẫn có thể xảy ra nếu hai bên chốt số liệu ở thời điểm khác nhau.",
  },
  {
    question: "Bao lâu số liệu được cập nhật một lần?",
    answer:
      "Số liệu phân tích được lấy mỗi ngày, ngay khi TikTok công bố ngày dữ liệu mới, và báo cáo được dựng lại sau đó. Đơn hàng, sản phẩm và tồn kho được đồng bộ thường xuyên hơn trong ngày. Giờ cập nhật gần nhất hiện ở đầu trang Phân tích.",
  },
  {
    question: "Shop nhỏ, ít đơn thì phân tích có ý nghĩa không?",
    answer:
      "Có, nhưng Juli nói rõ mức chắc chắn. Khi số đơn ít, thay đổi của một chỉ số dễ là dao động ngẫu nhiên; Juli gắn nhãn Tham khảo thay vì Rõ và gợi ý theo dõi thêm, thay vì đưa ra kết luận mạnh.",
  },
  {
    question: "Juli có phân tích GMV từ nhà sáng tạo (Liên kết) không?",
    answer:
      "Có ở mức toàn shop: luồng Liên kết xuất hiện ở Trang chủ cùng bốn luồng còn lại để bạn thấy toàn cảnh. Juli không dùng Liên kết để kết luận về một sản phẩm, vì phần lớn biến động ở đó đến từ nội dung của nhà sáng tạo chứ không từ trang sản phẩm của bạn.",
  },
  {
    question: "Xem phân tích có làm thay đổi gì trên shop không?",
    answer:
      "Không. Phân tích chỉ đọc dữ liệu. Mọi thay đổi trên shop đi qua thẻ đề xuất và chỉ được thực hiện khi bạn duyệt và xác nhận.",
  },
] as const;

export default function PhanTichShopPage() {
  return (
    <CapabilityPage
      eyebrow="Phân tích"
      faq={FAQ}
      heading="Phân tích TikTok Shop theo từng luồng truy cập: biết GMV tăng hay giảm vì đâu"
      ctaTitle="Xem shop của bạn đang hụt GMV ở đâu."
      heroChrome="Phân tích · Juli"
      heroShot={[
        {
          alt: "GMV chia theo 5 luồng truy cập (dữ liệu mẫu)",
          mobileVariants: CAP_PT_LUONG_MOBILE,
          variants: CAP_PT_LUONG,
        },
        {
          alt: "Phễu luồng Thẻ sản phẩm, ô CTOR được đánh dấu (dữ liệu mẫu)",
          mobileVariants: CAP_PT_PHEU_MOBILE,
          variants: CAP_PT_PHEU,
        },
      ]}
      lead={
        <>
          Juli tách GMV của shop thành năm luồng truy cập mà TikTok Shop ghi nhận, dựng phễu của từng
          luồng từ Lượt hiển thị đến GMV và chỉ ra chỉ số đang kéo GMV xuống, kèm danh sách sản phẩm và
          nội dung gây ra nhiều nhất. Báo cáo được dựng lại mỗi ngày từ dữ liệu của chính shop bạn.
        </>
      }
      path={PATH}
      related={[
        {
          href: "/san-pham/de-xuat-va-thuc-thi",
          title: "Đề xuất và thực thi",
          body: "Từ chỉ số nghẽn đến thẻ đề xuất cụ thể cho từng sản phẩm, và Juli thực hiện khi bạn duyệt.",
        },
        {
          href: "/san-pham/do-luong-gmv",
          title: "Đo lường GMV",
          body: "Mỗi thay đổi được đo ở ngày 7 và ngày 14 so với mốc trước khi áp dụng.",
        },
        {
          href: "/ket-noi/tiktok-shop",
          title: "Kết nối TikTok Shop",
          body: "Uỷ quyền chính thức, dữ liệu Juli đọc và những gì xảy ra trong giờ đầu sau khi kết nối.",
        },
        {
          href: "/san-pham",
          title: "Tổng quan sản phẩm",
          body: "Juli làm gì, dành cho ai và bảng giá.",
        },
      ]}
      screenshot={CAP_PT_LUONG[0]?.webp}
      service
      toc={[
        { id: "nam-luong", label: "Năm luồng truy cập" },
        { id: "pheu", label: "Phễu từng luồng" },
        { id: "chi-so-nghen", label: "Chỉ số nghẽn" },
        { id: "xep-hang", label: "Xếp hạng theo GMV" },
        { id: "khuyen-mai", label: "Khuyến mãi và ngày sale" },
        { id: "cap-nhat", label: "Cập nhật mỗi ngày" },
        { id: "cau-hoi", label: "Câu hỏi thường gặp" },
      ]}
    >
      <CapSection
        alt="Màn hình Phân tích của Juli: tiêu đề 'Thẻ sản phẩm: CTOR giảm 7 %', so sánh 30 ngày với 30 ngày trước, hai tab Sản phẩm và Nội dung, dòng chú thích các luồng Thẻ sản phẩm, Tab cửa hàng, Video, LIVE và Liên kết"
        caption="Đầu trang Phân tích: kết luận chính của 30 ngày gần nhất, và cách các luồng được chia vào tab Sản phẩm, tab Nội dung và Trang chủ."
        heading="Năm luồng truy cập tạo nên GMV của shop"
        id="nam-luong"
        image={CAP_PT_LUONG}
        mobileImage={CAP_PT_LUONG_MOBILE}
      >
        <P>
          TikTok Shop ghi nhận mỗi đơn hàng đến từ đâu. Trong mục Lưu lượng truy cập sản phẩm của Trung
          tâm nhà bán hàng, GMV và các chỉ số phễu được chia theo năm luồng: Thẻ sản phẩm của người bán,
          Tab Cửa hàng, Video của người bán, LIVE của người bán và Liên kết (video và LIVE của nhà sáng
          tạo). Juli dùng đúng cách chia đó, vì mỗi luồng có người xem khác nhau, lý do mua khác nhau và
          cách cải thiện khác nhau.
        </P>
        <StreamGrid />
        <P>
          Một shop có thể tăng GMV tổng trong khi một luồng quan trọng đang đi xuống. Nếu chỉ nhìn số tổng,
          bạn sẽ không thấy điều đó cho đến khi luồng tăng trưởng chững lại. Vì vậy, mọi phép so sánh
          trong Juli bắt đầu bằng câu hỏi: luồng nào đã thay đổi, và thay đổi bao nhiêu đồng mỗi ngày.
        </P>
        <H3>Nhóm khách tự tìm đến: Thẻ sản phẩm và Tab cửa hàng</H3>
        <P>
          Đây là những người mua tìm kiếm, lướt gợi ý hoặc vào trang cửa hàng rồi chạm vào sản phẩm của
          bạn. Những gì bạn kiểm soát trực tiếp, như ảnh bìa, tiêu đề, mô tả, giá và voucher, tác động
          mạnh nhất ở nhóm này. Trong Juli, hai luồng này nằm ở tab Sản phẩm của trang Phân tích, và CTOR
          (tỷ lệ từ nhấp đến đặt hàng) là chỉ số được theo dõi kỹ nhất.
        </P>
        <H3>Nhóm nội dung: Video, LIVE và Liên kết</H3>
        <P>
          Ở nhóm nội dung, người mua thấy sản phẩm qua một video hay một phiên LIVE. Lượt hiển thị và GMV
          là hai chỉ số chính; CTOR vẫn được hiển thị để tham khảo nhưng phụ thuộc nhiều vào trang sản
          phẩm. Video và LIVE của shop nằm ở tab Nội dung. Luồng Liên kết (nội dung của nhà sáng tạo)
          được theo dõi ở Trang chủ, để bạn thấy toàn cảnh, nhưng Juli không dùng nó để kết luận về một
          sản phẩm cụ thể.
        </P>
        <H3>Vì sao không dừng ở con số tổng của shop</H3>
        <P>
          Chỉ số trung bình của cả shop có thể đi ngang trong khi chỉ số của một luồng giảm rõ, chỉ vì một
          luồng khác tăng mạnh và che đi. Đó là lý do Juli luôn đọc từng luồng trước, rồi mới đến từng sản
          phẩm. Nếu bạn muốn hiểu kỹ hơn về các chỉ số, các bài viết trên{" "}
          <A href={BLOG_PATH}>blog của Juli</A> giải thích từng khái niệm bằng ví dụ.
        </P>
      </CapSection>

      <CapSection
        alt="Khối Thẻ sản phẩm trong Phân tích: GMV 3,6 triệu đồng mỗi ngày, năm ô Lượt hiển thị mỗi ngày, CTR, CTOR, AOV và GMV mỗi ngày, mỗi ô ghi phần trăm thay đổi và số đồng mỗi ngày mà chỉ số đó kéo GMV lên hoặc xuống"
        caption="Phễu của luồng Thẻ sản phẩm. Ô CTOR được Juli đánh dấu vì nó kéo GMV xuống nhiều nhất."
        heading="Phễu của từng luồng: từ Lượt hiển thị đến GMV"
        id="pheu"
        image={CAP_PT_PHEU}
        mobileImage={CAP_PT_PHEU_MOBILE}
      >
        <P>
          Với mỗi luồng, Juli dựng phễu theo cách TikTok Shop định nghĩa trong Học viện người bán (bài
          “Lưu lượng truy cập sản phẩm”). GMV của một luồng là tích của bốn chỉ số:
        </P>
        <FunnelDiagram
          caption="GMV = Lượt hiển thị sản phẩm × CTR × CTOR × AOV (SKU). Ví dụ minh hoạ: Juli đánh dấu bước có chênh lệch lớn nhất so với kỳ trước."
          highlight="ctor"
        />
        <Ul>
          <li>
            <strong>Lượt hiển thị sản phẩm</strong>: số lần sản phẩm xuất hiện trước người mua trên luồng
            đó.
          </li>
          <li>
            <strong>CTR (tỷ lệ nhấp)</strong> = lượt nhấp vào sản phẩm ÷ lượt hiển thị sản phẩm.
          </li>
          <li>
            <strong>CTOR</strong> = đơn hàng SKU ÷ lượt nhấp vào sản phẩm, tức tỷ lệ lượt nhấp dẫn đến
            đơn hàng.
          </li>
          <li>
            <strong>AOV (SKU)</strong> = GMV ÷ đơn hàng SKU, tức số tiền trung bình của một đơn hàng SKU.
          </li>
        </Ul>
        <P>
          Vì GMV là tích của bốn chỉ số, mỗi thay đổi về GMV có thể được tách thành bốn phần: phần do lượt
          hiển thị, phần do CTR, phần do CTOR và phần do AOV. Đây là cách Juli trả lời câu hỏi “GMV giảm vì
          ít người thấy, vì ít người bấm, hay vì người bấm vào không mua”.
        </P>
        <P>
          Muốn thử với số của một sản phẩm? <A href={FREE_TOOLS.gmvCalculator.href}>Công cụ tính GMV miễn phí</A>{" "}
          dựng phễu này từ bốn chỉ số ngay trên trình duyệt, không cần tài khoản.
        </P>
        <H3>Cách Juli tính, để số khớp với TikTok</H3>
        <Ul>
          <li>
            Mọi số trong bảng là trung bình mỗi ngày, so sánh 30 ngày gần nhất với 30 ngày ngay trước đó.
          </li>
          <li>
            Tỷ lệ của một kỳ được tính từ tổng của kỳ (tổng lượt nhấp ÷ tổng lượt hiển thị), giống cách
            Seller Center tính cho một khoảng ngày, chứ không lấy trung bình của các tỷ lệ hằng ngày.
          </li>
          <li>
            GMV là GMV của TikTok, gồm cả đơn đã huỷ và hoàn tiền. Juli không tự trừ bớt.
          </li>
        </Ul>
        <H3>Mỗi ô ghi số đồng mỗi ngày, không chỉ phần trăm</H3>
        <P>
          Một ô CTR giảm 5 % nghe có vẻ nghiêm trọng hơn một ô AOV giảm 3 %, nhưng điều quan trọng là mỗi
          thay đổi lấy đi bao nhiêu GMV. Dưới mỗi chỉ số, Juli ghi số đồng mỗi ngày mà thay đổi của chỉ số
          đó kéo GMV lên hoặc xuống. Bốn con số cộng lại bằng đúng mức thay đổi GMV của luồng, nên bạn biết
          chỗ nào đáng để tâm trước.
        </P>
        <H3>Khi TikTok không cung cấp một chỉ số</H3>
        <P>
          Không phải luồng nào cũng có đủ dữ liệu. Ví dụ, ở luồng Video, CTOR và AOV phụ thuộc vào trang
          sản phẩm nhiều hơn là vào chính video, nên Juli để các ô này màu xám với ghi chú “Phụ thuộc sản
          phẩm” và hướng bạn sang tab Sản phẩm. Khi một số liệu không có, Juli để trống và ghi rõ, không tự
          điền một con số ước đoán.
        </P>
      </CapSection>

      <CapSection
        alt="Khối Tab cửa hàng trong Phân tích: ô AOV 167 nghìn đồng giảm 2,1 % được đánh dấu Juli gợi ý, kéo GMV giảm 31 nghìn đồng mỗi ngày, bên dưới là bảng sản phẩm kéo AOV xuống với nhãn Rõ"
        caption="Ở luồng Tab cửa hàng, chỉ số kéo GMV xuống nhiều nhất là AOV; bảng bên dưới cho biết sản phẩm nào gây ra."
        heading="Tăng GMV từ chỉ số nghẽn: chỉ số nào đang kéo GMV xuống"
        id="chi-so-nghen"
        image={CAP_PT_NGHEN}
        mobileImage={CAP_PT_NGHEN_MOBILE}
      >
        <P>
          Sau khi tách GMV thành bốn phần, Juli đánh dấu “Juli gợi ý” lên chỉ số lấy đi nhiều GMV nhất của
          luồng đó. Đầu trang Phân tích tóm tắt thành một câu, ví dụ “Thẻ sản phẩm: CTOR giảm 7 %”, và
          thanh gợi ý bên cạnh cho biết chỉ số đó kéo GMV đi bao nhiêu đồng mỗi ngày, kèm nút xem các đề
          xuất liên quan.
        </P>
        <H3>So với dao động bình thường của chính chỉ số đó</H3>
        <P>
          Chỉ số trên TikTok Shop dao động mạnh từ ngày này sang ngày khác, nhất là với shop ít đơn. Một
          mức giảm chỉ được coi là đáng chú ý khi nó lớn hơn mức dao động bình thường của chính chỉ số đó
          trên chính luồng đó. Nhờ vậy, Juli không biến một tuần xấu ngẫu nhiên thành một “vấn đề”.
        </P>
        <H3>Lượt hiển thị khác ba chỉ số còn lại</H3>
        <P>
          Lượt hiển thị phụ thuộc nhiều vào cách TikTok phân phối, vào mùa vụ và vào nội dung của nhà sáng
          tạo. Chỉnh trang sản phẩm thường tác động rõ hơn đến CTR và CTOR. Juli vẫn hiển thị phần GMV do
          lượt hiển thị gây ra.
        </P>
        <H3>CTOR giảm: trước giỏ hàng hay sau giỏ hàng</H3>
        <P>
          Khi CTOR là chỉ số nghẽn, Juli tách tiếp thành hai bước. Nếu tỷ lệ thêm vào giỏ hàng giảm, vấn đề
          nằm trước giỏ hàng: giá, hình ảnh, mô tả hoặc đánh giá chưa thuyết phục. Nếu khách vẫn thêm vào
          giỏ nhưng ít đặt hàng hơn, vấn đề nằm sau giỏ hàng: voucher, phí vận chuyển, hoặc khách đang chờ
          một đợt flash sale. Hai trường hợp dẫn đến hai loại đề xuất rất khác nhau.
        </P>
      </CapSection>

      <CapSection
        alt="Bảng 5 sản phẩm kéo CTOR xuống: mỗi dòng có mã SKU, tên sản phẩm, CTOR trước và nay, số đồng GMV mỗi ngày bị mất, nhãn tin cậy Rõ hoặc Tham khảo và liên kết Xem đề xuất"
        caption="Bảng xếp hạng dưới ô CTOR: các dòng cộng lại bằng đúng số của ô, sản phẩm gây ảnh hưởng lớn nhất đứng đầu."
        heading="Xếp hạng sản phẩm và nội dung theo tác động lên GMV"
        id="xep-hang"
        image={CAP_PT_XEP_HANG}
        mobileImage={CAP_PT_XEP_HANG_MOBILE}
      >
        <P>
          Biết CTOR của Thẻ sản phẩm đang giảm mới là một nửa câu trả lời. Bấm vào một ô, Juli mở bảng chia
          con số của ô đó cho từng sản phẩm: CTOR trước và nay, số đồng GMV mỗi ngày mà sản phẩm đó làm mất
          (hoặc mang thêm), và nhãn tin cậy. Các dòng cộng lại bằng đúng con số trên ô, phần nhỏ được gộp
          vào dòng “Còn lại”.
        </P>
        <Ul>
          <li>
            <strong>Kéo xuống / Kéo lên</strong>: xem sản phẩm làm GMV giảm nhiều nhất, hoặc sản phẩm đang
            đóng góp tăng trưởng.
          </li>
          <li>
            <strong>Xem đề xuất</strong>: với sản phẩm đã có thẻ đề xuất, đi thẳng sang trang Quyết định.
            Sản phẩm chưa đủ cơ sở để đề xuất ghi “Chưa có đề xuất”.
          </li>
        </Ul>
        <H3>Xếp hạng nội dung: video và phiên LIVE</H3>
        <P>
          Ở tab Nội dung, Juli làm điều tương tự cho video và LIVE của shop: những video làm CTR giảm nhiều
          nhất, ngày đăng và sản phẩm được gắn, hoặc những phiên LIVE có người xem bấm vào sản phẩm nhưng ít
          chốt đơn. Từ một video, bạn mở được trang của sản phẩm được gắn trong đó.
        </P>
        <H3>Nhãn Rõ và Tham khảo</H3>
        <P>
          Mỗi dòng mang một nhãn tin cậy. <strong>Rõ</strong> nghĩa là cả hai kỳ có đủ đơn hàng và mức
          thay đổi nằm ngoài vùng dao động ngẫu nhiên. <strong>Tham khảo</strong> nghĩa là dữ liệu còn ít
          hoặc thay đổi chưa vượt khỏi mức nhiễu, nên Juli gợi ý theo dõi thêm thay vì kết luận. Cách đặt
          nhãn được giải thích kỹ hơn ở trang <A href="/san-pham/do-luong-gmv">Đo lường GMV</A>.
        </P>
        <H3>Từ xếp hạng đến hành động</H3>
        <P>
          Sản phẩm lấy đi nhiều GMV nhất đứng đầu bảng. Nếu sản phẩm đã có thẻ, bạn đi thẳng sang{" "}
          <A href="/san-pham/de-xuat-va-thuc-thi">thẻ đề xuất</A> của sản phẩm đó.
        </P>
      </CapSection>

      <CapSection
        alt="Khối Khuyến mãi trong Phân tích: số ngày có flash sale trong 60 ngày, mức giảm thật trung bình so với giá đang bán, tỷ lệ đơn dùng voucher, và bảng từng sản phẩm với loại khuyến mãi, mức giảm thật và GMV mỗi ngày trong và ngoài khuyến mãi"
        caption="Khối Khuyến mãi: flash sale, giảm giá sản phẩm và voucher của 60 ngày, với mức giảm thật của từng sản phẩm."
        heading="Khuyến mãi và ngày sale trong cùng bức tranh"
        id="khuyen-mai"
        image={CAP_PT_KHUYEN_MAI}
        mobileImage={CAP_PT_KHUYEN_MAI_MOBILE}
      >
        <P>
          Rất nhiều biến động của CTOR và AOV đến từ khuyến mãi: một đợt flash sale bắt đầu, một voucher hết
          hạn, hay một ngày sale lớn của sàn. Nếu phân tích bỏ qua khuyến mãi, bạn có thể sửa nhầm trang sản
          phẩm trong khi nguyên nhân nằm ở lịch giảm giá. Vì vậy, Juli đặt khuyến mãi ngay bên dưới các luồng.
        </P>
        <H3>Giảm thật, không phải giảm trên giá niêm yết</H3>
        <P>
          Khi một sản phẩm đã có giảm giá sản phẩm, một đợt flash sale chỉ thấp hơn mức giá đó vài phần trăm
          gần như không tạo khác biệt cho người mua. Juli tính “giảm thật” là giá flash sale so với giá đang
          bán ngay trước đó, và đánh dấu những đợt giảm quá nông. Bảng cũng so GMV mỗi ngày của sản phẩm
          trong và ngoài thời gian khuyến mãi.
        </P>
        <H3>Voucher của shop</H3>
        <P>
          Juli đếm tỷ lệ đơn đạt ngưỡng voucher trong số voucher đang chạy, để bạn thấy voucher có thực sự
          được dùng hay không. Juli đọc khuyến mãi và voucher ở chế độ chỉ đọc; việc tạo hay sửa khuyến mãi
          vẫn do bạn làm trên Seller Center.
        </P>
      </CapSection>

      <CapSection
        alt="Biểu đồ Lịch sale và chiến dịch: cột GMV mỗi ngày trong 60 ngày, các ngày flash sale của shop và ngày sale của TikTok như 9.9 và 10.10 được tô màu riêng, kèm ghi chú ngày sale sắp tới"
        caption="Lịch sale và chiến dịch: GMV mỗi ngày trong 60 ngày, ngày flash sale của shop và ngày sale của TikTok được đánh dấu."
        heading="Báo cáo cập nhật mỗi ngày: số liệu mới đến đâu"
        id="cap-nhat"
        image={CAP_PT_LICH_SALE}
        mobileImage={CAP_PT_LICH_SALE_MOBILE}
      >
        <P>
          Báo cáo Phân tích không phải một tệp bạn phải tải về. Nó nằm ngay trong Juli, ở Trang chủ và trang
          Phân tích, và được dựng lại mỗi ngày. Góc trên của màn hình luôn ghi giờ cập nhật gần nhất.
        </P>
        <H3>Nhịp lấy dữ liệu</H3>
        <Ul>
          <li>
            <strong>Số liệu phân tích</strong> (lượt hiển thị, lượt nhấp, đơn hàng SKU, GMV theo luồng):
            lấy mỗi ngày một lần, ngay khi TikTok công bố ngày dữ liệu mới. Số liệu phân tích của TikTok có
            độ trễ, nên ngày mới nhất thường là hôm qua.
          </li>
          <li>
            <strong>Đơn hàng, sản phẩm, tồn kho, đơn hoàn</strong>: đồng bộ nhiều lần trong ngày.
          </li>
          <li>
            <strong>Ngày bị thiếu</strong>: nếu một lần lấy dữ liệu thất bại, lần sau Juli lấy bù từ ngày
            cuối cùng đã có, nên báo cáo không bị hổng.
          </li>
        </Ul>
        <H3>Ngày sale được đánh dấu, không bị loại bỏ</H3>
        <P>
          Ngày 9.9 hay 10.10 làm GMV tăng vọt rồi giảm lại. Juli không xoá những ngày này khỏi dữ liệu, mà
          đánh dấu trên biểu đồ để bạn biết một thay đổi lớn có trùng với ngày sale hay không.
        </P>
        <H3>Lịch sử dữ liệu dài bao nhiêu</H3>
        <P>
          Ngay khi bạn kết nối, Juli đọc 60 ngày gần nhất để có đủ hai kỳ 30 ngày so sánh, rồi mỗi đêm tải
          thêm lịch sử cũ hơn, đến 180 ngày hoặc đến giới hạn mà TikTok cho phép. Chi tiết ở trang{" "}
          <A href="/ket-noi/tiktok-shop">Kết nối TikTok Shop</A>.
        </P>
        <Note>
          Ảnh trên trang này lấy từ bản demo của Juli với “Cửa hàng Mẫu Hoa Mai”, một shop minh hoạ. Các
          con số là dữ liệu mẫu, không phải kết quả của một shop thật.
        </Note>
      </CapSection>
    </CapabilityPage>
  );
}
