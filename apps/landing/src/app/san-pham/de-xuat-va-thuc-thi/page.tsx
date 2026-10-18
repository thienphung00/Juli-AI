import {
  A,
  BLOG_PATH,
  CapabilityPage,
  CapSection,
  Formula,
  H3,
  Note,
  Ol,
  P,
  Ul,
} from "../../../components/product/capability-page";
import { ProcessDiagram } from "../../../components/product/diagrams";
import {
  CAP_DX_HANG_CHO,
  CAP_DX_HOAN_TAC,
  CAP_DX_LUOT_CHAY,
  CAP_DX_LUOT_CHAY_MOBILE,
  CAP_DX_QUY_TAC,
  CAP_DX_QUY_TAC_MOBILE,
  CAP_DX_SELLER_CENTER,
  CAP_DX_THE,
  CAP_DX_TU_CHOI,
  CAP_DX_XAC_NHAN,
  CAP_DX_XAC_NHAN_MOBILE,
} from "../../../components/product/screens";
import { buildMetadata } from "../../../lib/seo";

/**
 * `/san-pham/de-xuat-va-thuc-thi` — capability page "Đề xuất & Thực thi"
 * (D43.1, D43.4, P33-C). Grounded in D13 (execution scope), D22 (recoverable
 * GMV), D24 (rules choose, LLM only writes; card limits and slots), D29 / D32
 * / D39 (trigger, KPI, channel) and the demo's Quyết định screens.
 */
const PATH = "/san-pham/de-xuat-va-thuc-thi";

export const metadata = buildMetadata(PATH);

const FAQ = [
  {
    question: "Juli có tự thay đổi shop của tôi mà không hỏi không?",
    answer:
      "Không. Một thay đổi chỉ được ghi lên TikTok Shop sau hai bước của bạn: bấm Duyệt trên thẻ, rồi xác nhận nội dung cụ thể trong lượt chạy. Không duyệt, không có gì thay đổi.",
  },
  {
    question: "Juli có đổi giá sản phẩm không?",
    answer:
      "Không. Với giá, Juli chỉ đưa ra đề xuất. Khuyến mãi như giảm giá sản phẩm, flash sale hay mua nhiều giảm nhiều do bạn tạo trên Seller Center theo hướng dẫn của Juli; Juli kiểm tra lại sau đó và bắt đầu đo.",
  },
  {
    question: "Nội dung do Juli viết có được kiểm tra trước không?",
    answer:
      "Có. Nội dung mới được kiểm tra độ dài, giọng văn và danh sách từ không được dùng mà bạn đặt trong Quy tắc trước khi hiện ra để bạn xác nhận. Bạn có thể sửa lại nội dung trước khi áp dụng.",
  },
  {
    question: "Nếu thay đổi làm kết quả tệ hơn thì sao?",
    answer:
      "Bạn bấm Hoàn tác. Juli tạo một lượt chạy khôi phục nội dung cũ đã lưu và bạn xác nhận lần cuối trước khi Juli ghi. Ở ngày thứ 7, nếu một chỉ số ra ngoài ngưỡng bạn cho phép, Juli sẽ hỏi bạn có muốn hoàn tác không. Juli không tự hoàn tác.",
  },
  {
    question: "Mỗi ngày tôi nhận bao nhiêu thẻ đề xuất?",
    answer:
      "Tối đa 5 thẻ mới mỗi ngày, 25 thẻ mỗi tuần và 30 thẻ đang mở cùng lúc. Bạn có thể giảm con số đang mở trong Quy tắc. Mỗi thẻ có hiệu lực 7 ngày.",
  },
  {
    question: "Tôi từ chối một thẻ thì nó có quay lại không?",
    answer:
      "Cùng một thay đổi cho cùng một sản phẩm chỉ có thể quay lại sau ít nhất 7 ngày. Lý do bạn chọn khi từ chối cũng làm loại thay đổi đó được ưu tiên thấp hơn cho shop của bạn trong thời gian sau.",
  },
] as const;

export default function DeXuatVaThucThiPage() {
  return (
    <CapabilityPage
      eyebrow="Đề xuất và thực thi"
      faq={FAQ}
      heading="Đề xuất tối ưu cho từng sản phẩm TikTok Shop, chỉ thực hiện khi bạn duyệt"
      ctaTitle="Để Juli chuẩn bị việc cần làm, bạn chỉ việc duyệt."
      heroChrome="Quyết định · Juli"
      heroShot={{
        alt: "Lượt chạy dừng ở bước Xác nhận một lần: tiêu đề và mô tả cũ, nội dung mới, nút Xác nhận thay đổi này (dữ liệu mẫu)",
        crop: 16 / 10,
        mobileVariants: CAP_DX_XAC_NHAN_MOBILE,
        variants: CAP_DX_XAC_NHAN,
      }}
      lead={
        <>
          Từ chỉ số đang kéo GMV xuống, Juli tạo thẻ đề xuất cho từng sản phẩm: vì sao, đổi gì, mục tiêu
          nào và GMV dự kiến bao nhiêu. Bạn duyệt hoặc từ chối. Với tiêu đề, mô tả và ảnh bìa, Juli thực
          hiện thay đổi trên TikTok Shop sau khi bạn xác nhận; với giá và khuyến mãi, Juli hướng dẫn để bạn
          tự làm trên Seller Center. Mọi thay đổi đều hoàn tác được.
        </>
      }
      path={PATH}
      related={[
        {
          href: "/san-pham/phan-tich-shop",
          title: "Phân tích shop",
          body: "Năm luồng truy cập, phễu của từng luồng và cách Juli tìm ra chỉ số nghẽn.",
        },
        {
          href: "/san-pham/do-luong-gmv",
          title: "Đo lường GMV",
          body: "Sau khi áp dụng, mỗi thay đổi được kiểm tra ở ngày 7 và chốt ở ngày 14.",
        },
        {
          href: "/ket-noi/tiktok-shop",
          title: "Kết nối TikTok Shop",
          body: "Juli được phép đọc gì, ghi gì, và cách ngắt kết nối.",
        },
        {
          href: "/privacy",
          title: "Chính sách bảo mật",
          body: "Điều kiện để Juli được thực hiện một thao tác trên shop thật.",
        },
      ]}
      screenshot={CAP_DX_THE[0]?.webp}
      service
      toc={[
        { id: "the-de-xuat", label: "Thẻ đề xuất" },
        { id: "khi-nao", label: "Khi nào có thẻ" },
        { id: "duyet", label: "Duyệt hoặc từ chối" },
        { id: "ai-lam", label: "Juli làm, bạn làm" },
        { id: "xac-nhan", label: "Xác nhận và ghi" },
        { id: "luot-chay", label: "Theo dõi lượt chạy" },
        { id: "hoan-tac", label: "Hoàn tác" },
        { id: "gioi-han", label: "Giới hạn và thời gian chờ" },
        { id: "cau-hoi", label: "Câu hỏi thường gặp" },
      ]}
    >
      <CapSection
        alt="Thẻ đề xuất cho sản phẩm Son môi số 12 đã mở rộng: CTOR từ 5,4 % lên mục tiêu 5,9 %, GMV dự kiến thêm 2,1 triệu đồng mỗi tháng, lý do khách thêm giỏ rồi bỏ, tiêu đề cũ bị gạch và tiêu đề mới, mô tả hiện tại và mô tả đề xuất, công thức tính GMV dự kiến"
        caption="Một thẻ đề xuất đã mở “Xem thêm”: lý do đầy đủ, nội dung trước và sau, và cách tính GMV dự kiến."
        heading="Tối ưu sản phẩm TikTok Shop bằng thẻ đề xuất: một sản phẩm, một chỉ số, một thay đổi"
        id="the-de-xuat"
        image={CAP_DX_THE}
        narrow
      >
        <P>
          Mỗi đề xuất của Juli là một thẻ trong trang Quyết định. Một thẻ nói về một sản phẩm, nhắm một chỉ
          số trên một luồng, và đề xuất một loại thay đổi. Trên thẻ có:
        </P>
        <Ul>
          <li>
            <strong>Chỉ số mục tiêu</strong>, ví dụ “CTOR 5,4 % → 5,9 %”: giá trị hiện tại,
            mục tiêu và mức tăng.
          </li>
          <li>
            <strong>GMV dự kiến</strong> mỗi tháng nếu đạt mục tiêu, ghi rõ là “ước tính theo quy tắc”.
          </li>
          <li>
            <strong>Lý do</strong> ngắn gọn (ví dụ “Khách thêm giỏ rồi bỏ”, “Ảnh bìa kém nổi bật”) và lý do
            đầy đủ khi mở “Xem thêm”, kể cả mã chẩn đoán sản phẩm mà TikTok trả về nếu có.
          </li>
          <li>
            <strong>Thay đổi đề xuất</strong>: Tiêu đề, Mô tả, Ảnh bìa, Giảm giá sản phẩm… cùng nội dung
            trước và sau.
          </li>
          <li>
            <strong>Ai thực hiện</strong>: Juli cập nhật sau khi bạn xác nhận, Juli tải lên ảnh bạn gửi, bạn
            thực hiện trên Seller Center, hoặc Juli soạn kịch bản để bạn quay.
          </li>
        </Ul>
        <H3>GMV dự kiến được tính thế nào</H3>
        <P>
          Juli dùng chính phép phân tách GMV của TikTok. Với một thẻ nhắm CTOR, phần GMV có thể lấy lại mỗi
          ngày là:
        </P>
        <Formula>Lượt nhấp × (CTOR mục tiêu − CTOR hiện tại) × AOV</Formula>
        <P>
          với số liệu trung bình 30 ngày. Thẻ nhắm CTR tính thêm bước CTOR, vì lượt nhấp tăng thêm chỉ thành
          GMV khi có người đặt hàng. Đây là ước tính theo quy tắc, không phải lời hứa; kết quả thật được đo
          sau khi áp dụng.
        </P>
        <H3>Mục tiêu nằm trong vùng đo được</H3>
        <P>
          Mục tiêu không được đặt tuỳ ý. Nó phải cao hơn mức dao động bình thường của chỉ số, nếu không sẽ
          không thể biết thay đổi có tác dụng hay không, nhưng cũng không được vượt quá vài lần mức dao động
          đó, để không hứa quá tay. Với sản phẩm có số liệu dao động mạnh, mục tiêu hiện dưới dạng một
          khoảng.
        </P>
        <H3>Đo trên đúng luồng mà thay đổi tác động</H3>
        <P>
          Ảnh bìa và tiêu đề chủ yếu được người mua nhìn thấy trên Thẻ sản phẩm, nên CTR của các thẻ này được
          đặt và đo trên luồng Thẻ sản phẩm (thẻ ghi “đo trên kênh Thẻ sản phẩm”). Thẻ mô tả và khuyến mãi
          nhắm CTOR; TikTok không tách đơn hàng SKU theo từng luồng, nên CTOR được đo trên tất cả các kênh.
        </P>
        <H3>Độ tin cậy</H3>
        <P>
          Mỗi thẻ có thể mang nhãn “Độ tin cậy: Cao, Vừa hoặc Thấp”, tính từ lượng dữ liệu và mức dao động
          của sản phẩm. Thẻ tạo ra ngay sau khi kết nối, khi Juli mới đọc 14 ngày, ghi “Đề xuất nhanh · dựa
          trên 14 ngày” với độ tin cậy Tham khảo.
        </P>
      </CapSection>

      <CapSection
        alt="Đầu trang Quyết định: tiêu đề 3 thẻ tối ưu để nâng CTOR (mọi kênh), ô Giữ ổn định với ngưỡng Lượt hiển thị, CTR và AOV cộng trừ 3 %, ô Quy tắc do bạn đặt với giọng văn và từ không được dùng"
        caption="Đầu trang Quyết định: ngưỡng giữ ổn định và quy tắc do người bán đặt, rồi các nhóm thẻ theo chỉ số."
        heading="Khi nào Juli mở một thẻ đề xuất"
        id="khi-nao"
        image={CAP_DX_QUY_TAC}
        mobileImage={CAP_DX_QUY_TAC_MOBILE}
      >
        <P>
          Một thẻ bắt đầu từ dữ liệu, không từ một danh sách mẹo chung. Juli đọc từng sản phẩm trên từng
          luồng và mở thẻ khi một trong bốn chỉ số của phễu (Lượt hiển thị, CTR, CTOR, AOV) giảm nhiều hơn
          mức dao động bình thường của nó, kể cả khi GMV tổng của sản phẩm vẫn giữ được nhờ một chỉ số khác
          tăng. Sau đó, Juli chọn thay đổi phù hợp với chỉ số đó: ảnh bìa hoặc tiêu đề cho CTR, mô tả hoặc
          giá cho CTOR, mua nhiều giảm nhiều cho AOV.
        </P>
        <H3>Xếp hạng theo GMV có thể lấy lại</H3>
        <P>
          Các ứng viên được xếp theo số GMV mỗi ngày mà chỉ số bị giảm đang lấy đi, giống bảng xếp hạng ở
          trang <A href="/san-pham/phan-tich-shop">Phân tích</A>. Sản phẩm bán chạy cũng được xét, vì một
          sản phẩm lớn mất vài phần trăm CTOR có thể mất nhiều tiền hơn một sản phẩm nhỏ mất một nửa.
        </P>
        <H3>Những điều kiện trước khi một thẻ hiện ra</H3>
        <Ul>
          <li>Có đủ dữ liệu: ít nhất khoảng 30 lượt nhấp hoặc 30 đơn trong khoảng thời gian xét.</li>
          <li>Thay đổi đó hợp lệ với TikTok Shop và với quy tắc của bạn.</li>
          <li>Sản phẩm không có một thay đổi khác đang được đo.</li>
          <li>Cùng thay đổi đó chưa bị từ chối hay hoàn tác trong 7 ngày qua.</li>
        </Ul>
        <H3>Quy tắc do bạn đặt</H3>
        <P>
          Trong Quy tắc, bạn đặt giọng văn, những từ không được dùng, giá vốn hoặc biên lợi nhuận tối thiểu,
          mức giảm giá tối đa và số thẻ mở cùng lúc. Juli không tự chọn các con số này. Một đề xuất giảm giá
          chỉ xuất hiện khi Juli biết giá vốn của sản phẩm, và luôn nằm trong biên lợi nhuận bạn cho phép.
        </P>
        <H3>Quy tắc chọn, AI chỉ viết</H3>
        <P>
          Chọn sản phẩm, chọn thay đổi và tính con số đều do quy tắc và phép tính đảm nhận. Mô hình AI chỉ
          được gọi sau khi bạn duyệt một thẻ, để soạn nội dung như tiêu đề, mô tả hay kịch bản video, và
          không bao giờ tạo ra con số trên thẻ. Bạn có thể đọc thêm về cách viết tiêu đề và mô tả trên{" "}
          <A href={BLOG_PATH}>blog của Juli</A>.
        </P>
      </CapSection>

      <CapSection
        alt="Hộp thoại Từ chối thẻ này với các lý do: thay đổi không hợp thương hiệu hoặc giọng văn, lý do hoặc số liệu chưa thuyết phục, tôi đang tự sửa sản phẩm này, sản phẩm sắp ngừng bán hoặc hết hàng, đang chạy chiến dịch khác, khác, kèm ô ghi chú"
        caption="Từ chối một thẻ: chọn một lý do, có thể ghi chú thêm. Juli không thay đổi gì trên sản phẩm."
        heading="Duyệt hoặc từ chối, theo cách của bạn"
        id="duyet"
        image={CAP_DX_TU_CHOI}
        narrow
      >
        <P>
          Mỗi thẻ có hai nút chính: <strong>Duyệt</strong> và <strong>Từ chối</strong>. Khi nhiều thẻ cùng
          nhắm một chỉ số, bạn có thể duyệt cả nhóm bằng một lần bấm. Duyệt chưa làm thay đổi gì trên shop:
          nó chỉ cho phép Juli bắt đầu chuẩn bị.
        </P>
        <ProcessDiagram
          caption="Một thay đổi trên shop cần hai lần đồng ý của bạn: Duyệt trên thẻ và Xác nhận nội dung trong lượt chạy. Mọi thay đổi Juli ghi đều lưu giá trị cũ để hoàn tác."
          label="Từ thẻ đề xuất đến thay đổi trên shop"
          steps={[
            {
              body: "Bạn duyệt hoặc từ chối thẻ. Duyệt chưa làm thay đổi gì trên shop.",
              marker: "Bước 1 · bạn",
              title: "Duyệt",
              you: true,
            },
            {
              body: "Juli soạn nội dung, bạn xác nhận lần cuối, rồi Juli ghi lên TikTok Shop và lưu giá trị cũ.",
              marker: "Bước 2",
              title: "Thực thi",
            },
            {
              body: "Bất cứ lúc nào, Juli khôi phục nội dung cũ đã lưu, cũng qua bước xác nhận của bạn.",
              marker: "Bước 3",
              title: "Hoàn tác",
            },
          ]}
        />
        <H3>Từ chối kèm lý do</H3>
        <P>
          Khi từ chối, bạn chọn một lý do: thay đổi không hợp thương hiệu, số liệu chưa thuyết phục, bạn
          đang tự sửa sản phẩm, sản phẩm sắp ngừng bán, đang chạy chiến dịch khác, hoặc lý do khác. Thẻ rời
          khỏi danh sách đề xuất, và Juli không đề xuất lại cùng thay đổi cho sản phẩm đó trong 7 ngày.
        </P>
        <H3>Lý do giúp đề xuất sau tốt hơn</H3>
        <P>
          Những lý do như “không hợp giọng văn” hay “số liệu chưa thuyết phục” làm loại thay đổi đó được ưu
          tiên thấp hơn cho shop của bạn trong khoảng hai tháng sau, và ảnh hưởng này nhạt dần theo thời
          gian. Những lý do mang tính hoàn cảnh, như đang tự sửa hay sắp ngừng bán, không bị tính.
        </P>
      </CapSection>

      <CapSection
        alt="Thẻ đề xuất Kem dưỡng ẩm ceramide: CTOR 4,2 % lên 5,0 %, lý do giá cao hơn đối thủ, thay đổi đề xuất giảm giá sản phẩm, nhãn Bạn thực hiện trên Seller Center và dòng hướng dẫn sau khi duyệt"
        caption="Một thẻ giảm giá: Juli không tạo khuyến mãi, mà hướng dẫn bạn làm trên Seller Center rồi bắt đầu đo khi bạn bấm “Đã áp dụng”."
        heading="Phần nào Juli làm, phần nào bạn làm"
        id="ai-lam"
        image={CAP_DX_SELLER_CENTER}
        narrow
      >
        <P>
          Juli chỉ tự thực hiện những thay đổi có thể kiểm soát và hoàn tác an toàn qua TikTok Shop Open
          API. Phần còn lại, Juli chuẩn bị sẵn để bạn làm nhanh nhất có thể.
        </P>
        <H3>AI viết tiêu đề và mô tả, chỉ áp dụng khi bạn duyệt</H3>
        <P>
          Với thẻ nhắm tiêu đề hoặc mô tả, Juli dùng AI để viết lại. Sau khi bạn duyệt thẻ, Juli đọc thông
          tin sản phẩm, chẩn đoán của TikTok và từ khoá liên quan, soạn tiêu đề hoặc mô tả sản phẩm mới
          rồi đưa bạn xem bản trước và sau; bạn sửa được nội dung trước khi áp dụng. Chỉ khi bạn xác nhận,
          Juli mới ghi tiêu đề hoặc mô tả mới lên TikTok Shop qua Open API và lưu lại nội dung cũ để có thể
          hoàn tác.
        </P>
        <P>
          Sau khi áp dụng, Juli đo thay đổi đó trên đúng luồng mà tiêu đề hay mô tả tác động: kiểm tra ở
          ngày 7 và chốt ở ngày 14, cách đo ở trang <A href="/san-pham/do-luong-gmv">Đo lường GMV</A>.
        </P>
        <H3>Ảnh bìa: chỉ với ảnh của bạn</H3>
        <P>
          Juli phân tích ảnh bìa hiện tại và đề xuất cần đổi gì, nhưng không tự tạo ảnh. Thẻ ảnh bìa ghi
          rõ Juli cần ảnh từ bạn: Juli hỏi ảnh, bạn tải ảnh lên, xác nhận, rồi Juli thay ảnh bìa.
        </P>
        <H3>Giá và khuyến mãi: Juli đề xuất, bạn áp dụng trên Seller Center</H3>
        <P>
          Juli không thay đổi giá sản phẩm. Với giảm giá sản phẩm, flash sale, mua nhiều giảm nhiều hay giảm
          phí vận chuyển, thẻ ghi “Bạn thực hiện trên Seller Center”. Sau khi duyệt, Juli đưa hướng dẫn từng
          bước với mức giảm cụ thể nằm trong quy tắc biên lợi nhuận của bạn. Bạn tạo khuyến mãi, bấm “Đã áp
          dụng”, Juli kiểm tra lại trên TikTok bằng quyền chỉ đọc và bắt đầu đo.
        </P>
        <H3>Video và LIVE: Juli soạn, bạn quay</H3>
        <P>
          Khi CTR của video hay khả năng chốt đơn trong LIVE của một sản phẩm giảm, Juli tạo thẻ “Juli soạn ·
          bạn làm”: kịch bản video mới, hoặc kịch bản cho người dẫn LIVE và thứ tự giỏ hàng. Bạn chọn dùng
          kịch bản, yêu cầu soạn lại hoặc bỏ qua, rồi tự quay hay lên LIVE. Juli nhận ra video mới gắn sản
          phẩm hoặc phiên LIVE tiếp theo bán sản phẩm và đo kết quả trên đó. Loại thẻ này không ghi gì lên
          TikTok Shop.
        </P>
      </CapSection>

      <CapSection
        alt="Lượt chạy cho Son môi số 12 đang chờ người bán: các bước đọc chẩn đoán TikTok, đọc thông tin sản phẩm, phân tích từ khoá, phân tích ảnh đã xong, bước xác nhận một lần đang chờ, hộp Juli đề xuất thay đổi sau với tiêu đề cũ và mới, mô tả cũ và mới, nút Không thực hiện và Xác nhận thay đổi này, thời gian còn hiệu lực"
        caption="Lượt chạy dừng ở bước “Xác nhận một lần”: bạn thấy chính xác nội dung sẽ được ghi, sửa được trước khi áp dụng."
        heading="Xác nhận lần cuối, rồi Juli mới ghi lên TikTok Shop"
        id="xac-nhan"
        image={CAP_DX_XAC_NHAN}
        mobileImage={CAP_DX_XAC_NHAN_MOBILE}
      >
        <P>
          Bấm Duyệt tạo ra một <strong>lượt chạy</strong>. Juli lần lượt đọc chẩn đoán của TikTok, đọc
          thông tin sản phẩm, phân tích từ khoá và ảnh, rồi soạn thay đổi. Lượt chạy dừng lại ở bước{" "}
          <strong>Xác nhận một lần</strong> và chờ bạn.
        </P>
        <Ol>
          <li>Bạn xem nội dung cũ (gạch ngang) và nội dung mới của từng phần sẽ thay đổi.</li>
          <li>Nếu muốn, bạn sửa nội dung trước khi áp dụng.</li>
          <li>
            Bạn bấm <strong>Xác nhận thay đổi này</strong>, hoặc <strong>Không thực hiện</strong> nếu đổi ý.
          </li>
          <li>Juli ghi lên TikTok Shop, TikTok duyệt lại trang sản phẩm, và Juli đặt lịch đo.</li>
        </Ol>
        <H3>Quyền ghi chỉ dùng một lần</H3>
        <P>
          Theo <A href="/privacy">Chính sách bảo mật</A>, một thao tác trên shop thật chỉ được thực hiện khi
          bạn đã chủ động duyệt đề xuất đó, và quyền ghi được cấp riêng cho đúng một sản phẩm, đúng một loại
          thao tác, có thời hạn và chỉ dùng được một lần. Hộp xác nhận hiển thị thời gian còn hiệu lực; hết
          hạn thì phải tạo lại.
        </P>
        <H3>Nội dung được kiểm tra trước khi đến tay bạn</H3>
        <P>
          Nội dung AI soạn được kiểm tra độ dài, giọng văn và danh sách từ không được dùng trong Quy tắc của
          bạn trước khi hiện ra, và được đối chiếu với thông tin của chính sản phẩm đó. Bạn vẫn là người
          đọc lại và quyết định cuối cùng.
        </P>
      </CapSection>

      <CapSection
        alt="Tab Đang thực hiện: lượt chạy Toner rau má 200ml đã áp dụng, tám bước có dấu kiểm và thời gian, bước Ghi lên TikTok Shop ghi đã ghi tiêu đề và giá trị cũ đã lưu, hộp Đã áp dụng thẻ chuyển sang Đo lường với ngày đo sơ bộ ngày 7 và chốt ngày 14, nút Hoàn tác, cột Hàng chờ thẻ tối ưu"
        caption="Tab Đang thực hiện: từng bước của lượt chạy có giờ thực hiện; khi xong, thẻ chuyển sang Đo lường với ngày đo cụ thể."
        heading="Theo dõi từng lượt chạy"
        id="luot-chay"
        image={CAP_DX_LUOT_CHAY}
        mobileImage={CAP_DX_LUOT_CHAY_MOBILE}
      >
        <P>
          Trong tab <strong>Đang thực hiện</strong>, mỗi lượt chạy hiện thành một dòng thời gian: bước nào
          đã xong, lúc mấy giờ, kết quả là gì. Khi Juli ghi lên TikTok Shop, bước đó ghi rõ đã đổi phần nào
          và “giá trị cũ đã lưu”. Bước cuối đặt lịch đo: ngày đo sơ bộ (ngày 7) và ngày chốt (ngày 14).
        </P>
        <H3>Một sản phẩm, một thay đổi tại một thời điểm</H3>
        <P>
          Juli chạy lần lượt và không bao giờ thực hiện hai thay đổi cùng lúc trên một sản phẩm. Nếu hai thay
          đổi chồng lên nhau, không ai biết thay đổi nào tạo ra kết quả. Đề xuất tiếp theo cho cùng sản phẩm
          có thể hiện ra ở ngày 7, nhưng chỉ được thực hiện sau khi thay đổi trước đã chốt ở ngày 14.
        </P>
      </CapSection>

      <CapSection
        alt="Hộp thoại Hoàn tác thay đổi này: Juli sẽ khôi phục tiêu đề cũ của Toner rau má 200ml, bạn xác nhận lần cuối trước khi Juli ghi, kết quả đo sẽ dừng; các lý do doanh số hoặc chỉ số giảm, khách phản hồi không tốt, nội dung sai thông tin sản phẩm, không hợp giọng thương hiệu, TikTok cảnh báo sản phẩm, khác"
        caption="Hoàn tác: chọn lý do, rồi Juli tạo một lượt chạy khôi phục nội dung cũ, cũng qua bước xác nhận."
        heading="Hoàn tác: quay về nội dung cũ bất cứ lúc nào"
        id="hoan-tac"
        image={CAP_DX_HOAN_TAC}
        narrow
      >
        <P>
          Mọi thay đổi Juli ghi lên TikTok Shop đều được lưu giá trị cũ. Nút <strong>Hoàn tác</strong> có
          ở lượt chạy đã áp dụng và trong phần Đo lường. Khi bấm, bạn chọn lý do, rồi Juli tạo một lượt chạy
          mới để khôi phục tiêu đề, mô tả hoặc ảnh bìa cũ. Lượt hoàn tác cũng dừng ở bước xác nhận trước khi
          ghi, và việc đo kết quả của thay đổi đó dừng lại.
        </P>
        <H3>Juli kiểm tra trước khi ghi đè</H3>
        <P>
          Trước khi khôi phục, Juli đọc lại sản phẩm trên TikTok Shop. Nếu nội dung đã bị sửa bên ngoài Juli
          sau lần thay đổi, Juli không ghi đè và báo cho bạn biết, để không xoá mất chỉnh sửa của chính bạn.
        </P>
        <H3>Những gì không cần hoặc không thể hoàn tác qua Juli</H3>
        <Ul>
          <li>Khuyến mãi do bạn tạo: muốn dừng, bạn tắt khuyến mãi trên Seller Center, Juli tự ghi nhận.</li>
          <li>Thẻ “Juli soạn · bạn làm”: Juli không ghi gì lên TikTok Shop nên không có gì để hoàn tác.</li>
        </Ul>
        <H3>Juli hỏi, bạn quyết định</H3>
        <P>
          Ở ngày thứ 7, nếu một chỉ số bạn muốn giữ ổn định ra ngoài ngưỡng cho phép, Juli hỏi bạn có muốn
          hoàn tác không. Juli không bao giờ tự hoàn tác. Cách đo được giải thích ở trang{" "}
          <A href="/san-pham/do-luong-gmv">Đo lường GMV</A>.
        </P>
      </CapSection>

      <CapSection
        alt="Cột Hàng chờ thẻ tối ưu: Juli chạy lần lượt, không bao giờ hai thay đổi cùng lúc trên một sản phẩm; Son môi số 12 đang chờ bạn, Toner rau má 200ml đã áp dụng"
        caption="Hàng chờ thẻ tối ưu: các lượt chạy được xử lý lần lượt."
        heading="Giới hạn số thẻ và thời gian chờ"
        id="gioi-han"
        image={CAP_DX_HANG_CHO}
        narrow
      >
        <P>
          Quá nhiều đề xuất cùng lúc khiến người bán khó theo kịp, và cũng khó đo kết quả. Juli giữ nhịp đề
          xuất bằng một số giới hạn cố định, giống nhau cho mọi shop:
        </P>
        <Ul>
          <li>Tối đa 5 thẻ mới mỗi ngày, 25 thẻ mỗi tuần, và 30 thẻ đang mở cùng lúc.</li>
          <li>
            Mỗi ngày, thẻ mới được chia theo loại: đến 3 thẻ Juli thực hiện (tiêu đề, mô tả, ảnh bìa), 1 thẻ
            bạn làm trên Seller Center và 1 thẻ nội dung video hoặc LIVE. Không có ứng viên tốt thì ô đó để
            trống, Juli không lấp bằng thẻ kém hơn.
          </li>
          <li>Bạn có thể giảm số thẻ mở cùng lúc trong Quy tắc (từ 5 đến 30).</li>
          <li>
            Mỗi thẻ có hiệu lực 7 ngày, và ở lại ít nhất 3 ngày dù thứ hạng thay đổi. Số liệu trên thẻ được
            cập nhật mỗi ngày.
          </li>
          <li>
            Thẻ bị rút sớm chỉ khi không còn hợp lệ: sản phẩm bị sửa bên ngoài Juli, hết hàng, hoặc chỉ số
            đã đạt mục tiêu.
          </li>
          <li>
            Sau khi hết hạn, bị từ chối, không thực hiện hoặc hoàn tác, cùng thay đổi cho cùng sản phẩm chỉ
            quay lại sau ít nhất 7 ngày.
          </li>
        </Ul>
        <H3>Ngày đầu tiên sau khi kết nối</H3>
        <P>
          Vài phút sau khi bạn kết nối shop, Juli đọc nhanh 14 ngày gần nhất và có thể tạo 1 đến 3 “đề xuất
          nhanh” về ảnh bìa, tiêu đề hoặc mô tả. Khi chẩn đoán đầy đủ trên 60 ngày hoàn tất, các thẻ còn lại
          trong ngày được lấp đầy. Xem thêm ở trang <A href="/ket-noi/tiktok-shop">Kết nối TikTok Shop</A>.
        </P>
        <Note>
          Ảnh trên trang này lấy từ bản demo của Juli với “Cửa hàng Mẫu Hoa Mai”, một shop minh hoạ. Các
          con số và nội dung là dữ liệu mẫu; thao tác trong bản demo không ghi gì lên TikTok Shop.
        </Note>
      </CapSection>
    </CapabilityPage>
  );
}
