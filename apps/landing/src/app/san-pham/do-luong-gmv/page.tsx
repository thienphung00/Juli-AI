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
import { ProcessDiagram } from "../../../components/product/diagrams";
import {
  CAP_DL_HOC,
  CAP_DL_HOC_MOBILE,
  CAP_DL_MUC_TIEU,
  CAP_DL_MUC_TIEU_MOBILE,
  CAP_DL_NGAY_14,
  CAP_DL_NGAY_14_MOBILE,
  CAP_DL_NGAY_7,
  CAP_DL_NGAY_7_MOBILE,
  CAP_DL_TANG_THEM,
  CAP_DL_TANG_THEM_MOBILE,
  CAP_DL_TIN_CAY,
  CAP_DL_TIN_CAY_MOBILE,
} from "../../../components/product/screens";
import { buildMetadata } from "../../../lib/seo";

/**
 * `/san-pham/do-luong-gmv` — capability page "Đo lường" (D43.1, D43.4, P33-C).
 * Grounded in D14 (day 7 / day 14), D29 (bands, KPI, verdict labels), D30
 * (frozen baseline, external changes), D31.7 (change strength), D24.6
 * (per-shop calibration and reasons) and D40.8 (when a lever counts as
 * learned). D34 control groups are not shipped to sellers, so the page makes
 * no control-group claim (D60.3). No results are quoted:
 * there are none to quote yet (D43.3).
 */
const PATH = "/san-pham/do-luong-gmv";

export const metadata = buildMetadata(PATH);

const FAQ = [
  {
    question: "Vì sao phải chờ đến ngày 14 mới chốt kết quả?",
    answer:
      "Số liệu TikTok Shop dao động mạnh theo ngày trong tuần, theo đợt sale và theo cách TikTok phân phối. Bảy ngày thường chưa đủ để tách tác động của một thay đổi khỏi dao động đó, nên ngày 7 chỉ là kiểm tra giữa chừng, còn ngày 14 mới là kết quả chốt.",
  },
  {
    question: "Juli có nhận công cho mọi lần GMV tăng không?",
    answer:
      "Không. Một kết quả chỉ được coi là Đạt khi chỉ số mục tiêu tăng rõ hơn mức dao động bình thường, chạm mục tiêu và GMV không giảm. Nếu trong thời gian đo có thay đổi khác như bạn tự sửa tiêu đề hay mở khuyến mãi, kết quả ghi rõ là bị ảnh hưởng bởi thay đổi khác.",
  },
  {
    question: "Ngày 7 mà kết quả xấu thì sao?",
    answer:
      "Nếu một chỉ số bạn muốn giữ ổn định ra ngoài ngưỡng cho phép, Juli hỏi bạn có muốn hoàn tác không, kèm số liệu cụ thể. Bạn có thể hoàn tác hoặc giữ thay đổi để đo tiếp đến ngày 14. Juli không tự hoàn tác.",
  },
  {
    question: "GMV dự kiến trên thẻ có phải cam kết không?",
    answer:
      "Không. GMV dự kiến là ước tính theo quy tắc, tính từ số liệu 30 ngày của sản phẩm. Kết quả thật là số đo được ở ngày 14, và hai con số này được đặt cạnh nhau để bạn so sánh.",
  },
  {
    question: "Juli có công bố kết quả trung bình của khách hàng không?",
    answer:
      "Chưa. Juli chỉ công bố hiệu quả của một loại thay đổi khi kết quả đo được đủ nhiều và nhất quán giữa các shop. Đến khi đó, trang này mô tả cách đo, không đưa ra con số kết quả.",
  },
] as const;

export default function DoLuongGmvPage() {
  return (
    <CapabilityPage
      eyebrow="Đo lường"
      faq={FAQ}
      heading="Đo lường GMV sau mỗi thay đổi: kiểm tra ngày 7, chốt kết quả ngày 14"
      ctaTitle="Biết mỗi thay đổi đã làm gì cho GMV của shop."
      heroChrome="Đo lường · Juli"
      heroShot={[
        {
          alt: "Mục tiêu và ngưỡng giữ ổn định của một thay đổi: chỉ số mục tiêu CTR đo trên kênh Thẻ sản phẩm, GMV dự kiến, các chỉ số không được lệch (dữ liệu mẫu)",
          mobileVariants: CAP_DL_MUC_TIEU_MOBILE,
          variants: CAP_DL_MUC_TIEU,
        },
        {
          alt: "Bảng kết quả ngày 7: chỉ số chính Đang lên, các chỉ số khác Giữ ổn định, GMV mỗi ngày ghi Sơ bộ (dữ liệu mẫu)",
          mobileVariants: CAP_DL_TANG_THEM_MOBILE,
          variants: CAP_DL_TANG_THEM,
        },
      ]}
      lead={
        <>
          Một đề xuất chỉ có giá trị khi biết nó có tác dụng hay không. Sau mỗi thay đổi, Juli so sánh chỉ
          số mục tiêu với mốc 14 ngày trước khi áp dụng, kiểm tra giữa chừng ở ngày 7, chốt ở ngày 14 và
          ghi rõ mức chắc chắn của kết quả. Kết quả đó quay lại quyết định thứ tự đề xuất tiếp theo cho shop
          của bạn.
        </>
      }
      path={PATH}
      related={[
        {
          href: "/san-pham/de-xuat-va-thuc-thi",
          title: "Đề xuất và thực thi",
          body: "Thẻ đề xuất, bước xác nhận, Hoàn tác và các giới hạn.",
        },
        {
          href: "/san-pham/phan-tich-shop",
          title: "Phân tích shop",
          body: "Năm luồng truy cập và phễu Lượt hiển thị → CTR → CTOR → AOV → GMV.",
        },
        {
          href: BLOG_PATH,
          title: "Blog",
          body: "Bài viết về chỉ số TikTok Shop và cách đọc chúng.",
        },
        {
          href: "/san-pham",
          title: "Tổng quan sản phẩm",
          body: "Juli làm gì, dành cho ai và bảng giá.",
        },
      ]}
      screenshot={CAP_DL_NGAY_7[0]?.webp}
      service
      toc={[
        { id: "truoc-khi-ap-dung", label: "Trước khi áp dụng" },
        { id: "ngay-7", label: "Ngày 7" },
        { id: "ngay-14", label: "Ngày 14" },
        { id: "tang-them", label: "Tác động tăng thêm" },
        { id: "do-tin-cay", label: "Nhãn độ tin cậy" },
        { id: "hoc", label: "Juli học từ kết quả" },
        { id: "cau-hoi", label: "Câu hỏi thường gặp" },
      ]}
    >
      <CapSection
        alt="Khối Mục tiêu và Ngưỡng giữ ổn định của sản phẩm Toner rau má 200ml: chỉ số mục tiêu CTR đo trên kênh Thẻ sản phẩm 3,2 % lên 3,5 %, GMV dự kiến 60 nghìn đồng mỗi ngày, bảng chỉ số không được lệch gồm Lượt hiển thị, CTOR, AOV với giá trị trước, ngưỡng cộng trừ 3 % và khoảng được phép dao động"
        caption="Trước khi đo: chỉ số mục tiêu, GMV dự kiến và khoảng dao động cho phép của các chỉ số còn lại, tính trên trung bình mỗi ngày của 14 ngày trước khi áp dụng."
        heading="Trước khi áp dụng: mục tiêu, mốc so sánh và ngưỡng giữ ổn định"
        id="truoc-khi-ap-dung"
        image={CAP_DL_MUC_TIEU}
        mobileImage={CAP_DL_MUC_TIEU_MOBILE}
      >
        <P>
          Việc đo bắt đầu trước khi thay đổi được ghi lên shop. Khi bạn duyệt và khi Juli thực hiện, Juli
          chụp lại trạng thái của sản phẩm: chuỗi số liệu 14 ngày trước đó, giá, các khuyến mãi đang chạy và
          nội dung trang sản phẩm. Đó là <strong>mốc so sánh</strong>, cố định từ thời điểm áp dụng.
        </P>
        <ProcessDiagram
          caption="Mọi con số là trung bình mỗi ngày, so với mốc 14 ngày trước khi áp dụng. Ngày 7 là kiểm tra giữa chừng, ngày 14 là kết quả chốt."
          label="Lịch đo một thay đổi"
          steps={[
            {
              body: "Juli chụp lại mốc so sánh: 14 ngày số liệu, giá, khuyến mãi và nội dung trang sản phẩm.",
              marker: "Trước khi áp dụng",
              title: "Mốc so sánh",
            },
            {
              body: "Kiểm tra giữa chừng: Đang lên hoặc Chưa rõ. Nếu một chỉ số ra ngoài ngưỡng, Juli hỏi bạn có muốn hoàn tác không.",
              marker: "Ngày 7",
              title: "Kết quả sơ bộ",
            },
            {
              body: "Đạt, Đạt · chưa chắc chắn, Một phần hoặc Không đạt, đặt cạnh GMV dự kiến ban đầu.",
              marker: "Ngày 14",
              title: "Kết quả chốt",
            },
          ]}
          variant="timeline"
        />
        <H3>Một chỉ số mục tiêu, trên đúng luồng</H3>
        <P>
          Mỗi thay đổi có một chỉ số mục tiêu, ví dụ CTR trên luồng Thẻ sản phẩm, với giá trị hiện tại và
          giá trị mục tiêu. Một sản phẩm chỉ có một chỉ số mục tiêu tại một thời điểm: nếu cùng lúc đổi để
          tăng CTR và CTOR, không thể biết thay đổi nào tạo ra kết quả.
        </P>
        <H3>Đo trên đúng luồng mà thay đổi tác động</H3>
        <P>
          Ảnh bìa, tiêu đề và mô tả chủ yếu được người mua thấy trên Thẻ sản phẩm, nên lượt hiển thị và CTR
          của các thay đổi này được đo trên luồng Thẻ sản phẩm, không bị pha loãng bởi lượt xem từ video hay
          LIVE. TikTok không tách đơn hàng SKU theo từng luồng cho từng sản phẩm, nên CTOR và AOV được đo
          trên tất cả các kênh. Khi luồng Thẻ sản phẩm của một sản phẩm có quá ít dữ liệu, Juli đo trên tất
          cả các kênh và ghi rõ điều đó trên thẻ.
        </P>
        <H3>Ngưỡng giữ ổn định cho các chỉ số còn lại</H3>
        <P>
          Một tiêu đề mới có thể tăng CTR nhưng làm giảm lượt hiển thị. Vì vậy, mỗi chỉ số không phải mục
          tiêu có một khoảng được phép dao động, gọi là ngưỡng giữ ổn định. Juli đề xuất ngưỡng dựa trên mức
          dao động bình thường của chính chỉ số đó, và bạn có thể chỉnh trong Quy tắc.
        </P>
        <H3>Vì sao mốc là 14 ngày</H3>
        <P>
          Doanh số trên TikTok Shop có nhịp theo ngày trong tuần: cuối tuần, ngày lương hay ngày sale khác
          hẳn ngày thường. Một mốc gồm hai tuần trọn vẹn chứa cả hai nhịp đó, nên so sánh với mốc ít bị lệch
          vì thời điểm áp dụng rơi vào đầu hay cuối tuần. Mọi con số trong phần đo là trung bình mỗi ngày,
          để hai khoảng có độ dài khác nhau vẫn so được với nhau.
        </P>
        <H3>GMV dự kiến được lưu lại để so sánh</H3>
        <P>
          GMV dự kiến tính ở thời điểm đề xuất được lưu cùng thay đổi. Đến ngày 14, kết quả thật được đặt
          cạnh con số này, để cả bạn và Juli biết ước tính đã sát đến đâu.
        </P>
      </CapSection>

      <CapSection
        alt="Màn hình Đo lường ngày 7 của Toner rau má 200ml: tiêu đề Ngày 7 CTR đang lên, các chỉ số khác trong khoảng; các bước đọc dữ liệu 7 ngày sau thay đổi, so chỉ số mục tiêu, so ngưỡng giữ ổn định, báo kết quả sơ bộ đã xong và bước chờ chốt ngày 14"
        caption="Ngày 7: Juli so 7 ngày sau thay đổi với 14 ngày trước, kiểm tra chỉ số mục tiêu và các ngưỡng giữ ổn định."
        heading="Ngày 7: kiểm tra giữa chừng"
        id="ngay-7"
        image={CAP_DL_NGAY_7}
        mobileImage={CAP_DL_NGAY_7_MOBILE}
        narrow
      >
        <P>Bảy ngày sau khi áp dụng, Juli chạy một lượt kiểm tra gồm các bước:</P>
        <Ol>
          <li>Đọc dữ liệu 7 ngày sau thay đổi và so với trung bình 14 ngày trước khi đổi.</li>
          <li>
            So chỉ số mục tiêu: <strong>Đang lên</strong> nếu đang tiến về mục tiêu, <strong>Chưa rõ</strong>{" "}
            nếu chưa thấy khác biệt.
          </li>
          <li>So từng chỉ số còn lại với ngưỡng giữ ổn định.</li>
          <li>Báo kết quả sơ bộ, hoặc hỏi bạn có muốn hoàn tác không.</li>
        </Ol>
        <H3>Khi một chỉ số ra ngoài ngưỡng</H3>
        <P>
          Nếu một chỉ số bạn muốn giữ ổn định đã ra ngoài khoảng cho phép, Juli hiện câu hỏi “Hoàn tác?” kèm
          số liệu cụ thể: chỉ số nào, giá trị bao nhiêu, ngoài khoảng nào. Bạn chọn <strong>Hoàn tác</strong>{" "}
          hoặc <strong>Giữ thay đổi</strong>. Nếu giữ, Juli đo tiếp đến ngày 14 và ghi chú rằng chỉ số đó
          đã ra ngoài khoảng ở ngày 7. Juli không tự hoàn tác.
        </P>
        <H3>Ngày 7 không phải kết luận</H3>
        <P>
          Kết quả ngày 7 được ghi là sơ bộ. Với sản phẩm có số liệu dao động mạnh, Juli chỉ đánh giá ở ngày
          14. Trong thời gian này, đề xuất tiếp theo cho cùng sản phẩm có thể đã hiện ra, nhưng chỉ được
          thực hiện sau khi thay đổi hiện tại chốt ở ngày 14.
        </P>
      </CapSection>

      <CapSection
        alt="Phần cuối lượt chạy đã áp dụng: bước TikTok duyệt lại trang sản phẩm, bước kết thúc và đặt lịch đo với ngày đo sơ bộ 17/10 ngày 7 và chốt 24/10 ngày 14, hộp Đã áp dụng thẻ chuyển sang Đo lường, nút Hoàn tác"
        caption="Ngày chốt được đặt ngay khi thay đổi được áp dụng: ngày 7 đo sơ bộ, ngày 14 chốt."
        heading="Ngày 14: kết quả chốt"
        id="ngay-14"
        image={CAP_DL_NGAY_14}
        mobileImage={CAP_DL_NGAY_14_MOBILE}
      >
        <P>
          Ở ngày 14, Juli đọc lại toàn bộ 14 ngày sau thay đổi, so với mốc 14 ngày trước, và gắn một trong
          các nhãn sau:
        </P>
        <Ul>
          <li>
            <strong>Đạt</strong>: chỉ số mục tiêu tăng rõ, chạm mục tiêu và GMV giữ được.
          </li>
          <li>
            <strong>Đạt · chưa chắc chắn</strong>: chạm mục tiêu, nhưng mức tăng chỉ gấp một đến hai lần mức
            dao động bình thường, nên chưa loại trừ được may rủi.
          </li>
          <li>
            <strong>Một phần</strong>: chỉ tăng rõ hoặc chỉ chạm mục tiêu, hoặc dữ liệu quá ít để chốt rõ.
          </li>
          <li>
            <strong>Không đạt</strong>: không tăng rõ và không chạm mục tiêu.
          </li>
        </Ul>
        <H3>Bị ảnh hưởng bởi thay đổi khác</H3>
        <P>
          Juli theo dõi những thay đổi diễn ra bên ngoài Juli: bạn tự sửa tiêu đề, đổi giá, mở hay tắt một
          khuyến mãi. Nếu một thay đổi như vậy rơi vào thời gian đo, kết quả ghi rõ “Bị ảnh hưởng bởi thay
          đổi khác”, kèm thay đổi đó và ngày xảy ra, thay vì ghi công cho đề xuất của Juli.
        </P>
        <H3>Sau ngày 14</H3>
        <P>
          Kết quả chốt được lưu lại cùng GMV dự kiến ban đầu, và dùng để điều chỉnh thứ tự các đề xuất sau
          (xem phần cuối trang). Sản phẩm có thể nhận đề xuất tiếp theo nếu dữ liệu cho thấy vẫn còn chỗ để
          cải thiện.
        </P>
      </CapSection>

      <CapSection
        alt="Bảng kết quả ngày 7: CTR chỉ số chính từ 3,2 % mục tiêu 3,5 % thực tế 3,4 % đánh giá Đang lên; Lượt hiển thị mỗi ngày, CTOR và AOV nằm trong khoảng cho phép với đánh giá Giữ ổn định; GMV mỗi ngày tăng 38 nghìn đồng ghi Sơ bộ; nút Hoàn tác"
        caption="Bảng so sánh: mỗi chỉ số có giá trị trước, mục tiêu hoặc khoảng cho phép, giá trị thực tế và đánh giá."
        heading="Tác động tăng thêm, không chỉ là trước và sau"
        id="tang-them"
        image={CAP_DL_TANG_THEM}
        mobileImage={CAP_DL_TANG_THEM_MOBILE}
      >
        <P>
          So sánh trước và sau là bước đầu, nhưng chưa đủ. Juli đặt mỗi mức thay đổi cạnh mức dao động bình
          thường của chỉ số đó, rồi mới gọi nó là một tác động.
        </P>
        <H3>Độ mạnh của thay đổi</H3>
        <P>
          Juli tính mức dao động của trung bình mỗi ngày trong cả hai khoảng (trước và sau), rồi so mức thay
          đổi với nó. Thay đổi lớn hơn hai lần mức dao động được coi là rõ; từ một đến hai lần là có thể đã
          thay đổi; dưới một lần là vẫn trong dao động bình thường. Một kết quả yếu không bao giờ được gắn
          nhãn mạnh hơn.
        </P>
        <H3>Vì sao trước – sau dễ đánh giá quá cao</H3>
        <P>
          Thẻ đề xuất thường được tạo ra đúng lúc một sản phẩm vừa giảm. Nhiều chỉ số sau một đợt giảm sẽ tự
          hồi lại phần nào, dù không ai làm gì. Nếu chỉ so trước và sau, phần hồi tự nhiên đó dễ bị tính là
          tác dụng của thay đổi. Đó là lý do Juli dùng mức dao động, ngưỡng giữ ổn định và ghi chú thay đổi
          bên ngoài, thay vì một phép trừ đơn giản.
        </P>
      </CapSection>

      <CapSection
        alt="Bảng video tác động CTR nhiều nhất trong tab Nội dung: ba video với CTR trước và nay, GMV mỗi ngày bị mất, nhãn tin cậy Rõ cho hai video và Tham khảo cho một video"
        caption="Nhãn Rõ và Tham khảo trên từng dòng của trang Phân tích."
        heading="Nhãn độ tin cậy: đọc thế nào"
        id="do-tin-cay"
        image={CAP_DL_TIN_CAY}
        mobileImage={CAP_DL_TIN_CAY_MOBILE}
      >
        <P>
          Juli không giấu sự không chắc chắn. Ở mỗi nơi có một kết luận, Juli ghi kèm mức tin cậy của nó, và
          những con số kém chắc chắn không được trình bày như con số chắc chắn.
        </P>
        <H3>Trong Phân tích: Rõ và Tham khảo</H3>
        <P>
          <strong>Rõ</strong> khi cả hai kỳ có đủ đơn hàng (khoảng 30 đơn mỗi bên trở lên) và khoảng tin
          cậy của mức thay đổi không chứa 0. <strong>Tham khảo</strong> khi dữ liệu ít hơn hoặc thay đổi vẫn
          nằm trong vùng nhiễu. Dòng Tham khảo đi kèm gợi ý theo dõi thêm.
        </P>
        <H3>Trên thẻ đề xuất: Cao, Vừa, Thấp</H3>
        <P>
          Độ tin cậy của thẻ tính từ lượng dữ liệu và mức dao động của sản phẩm trên luồng đó. Sản phẩm dao
          động mạnh nhận độ tin cậy Thấp, mục tiêu hiện dưới dạng một khoảng và chỉ được đánh giá ở ngày 14.
          Đề xuất nhanh tạo ngay sau khi kết nối, dựa trên 14 ngày, mang nhãn Tham khảo.
        </P>
        <H3>Khi chưa đủ dữ liệu</H3>
        <P>
          Juli tìm khoảng thời gian ngắn nhất (14, 30 rồi 60 ngày) có đủ khoảng 30 lượt nhấp hoặc 30 đơn để
          đánh giá một sản phẩm. Nếu ngay cả 60 ngày cũng không đủ, sản phẩm được ghi là ít dữ liệu và Juli
          không đưa ra chẩn đoán cho nó.
        </P>
      </CapSection>

      <CapSection
        alt="Nhóm thẻ tối ưu để nâng CTOR trên mọi kênh với GMV dự kiến cộng 7,2 triệu đồng mỗi tháng ghi là ước tính, hai thẻ Son môi số 12 và Kem dưỡng ẩm ceramide"
        caption="Thứ tự các thẻ trong một nhóm phản ánh GMV có thể lấy lại, đã điều chỉnh theo kết quả đo trước đó của shop."
        heading="Juli học từ kết quả đã đo"
        id="hoc"
        image={CAP_DL_HOC}
        mobileImage={CAP_DL_HOC_MOBILE}
      >
        <P>
          Mỗi kết quả ngày 14 quay lại quyết định đề xuất tiếp theo. Cách học hiện nay đơn giản và minh bạch,
          vì một shop chỉ có vài chục thay đổi được đo mỗi tháng.
        </P>
        <H3>Theo từng loại thay đổi, trong shop của bạn</H3>
        <P>
          Với mỗi loại thay đổi (ảnh bìa, tiêu đề, mô tả, giảm giá…), Juli giữ một hệ số so sánh GMV thực tế
          với GMV dự kiến của các lần đã đo trong shop. Loại thay đổi chưa được đo đứng ở mức trung tính; loại
          đã mang lại đúng như dự kiến được xếp lên trước, loại thường không đạt được xếp xuống. Khi thứ tự
          đã được điều chỉnh, thẻ ghi “Thứ tự đề xuất đã điều chỉnh theo kết quả trước của shop”. Con số GMV
          dự kiến trên thẻ vẫn là ước tính theo quy tắc, để còn so được với kết quả thật.
        </P>
        <H3>Theo lựa chọn của bạn</H3>
        <P>
          Lý do bạn chọn khi từ chối, không thực hiện hoặc hoàn tác làm loại thay đổi đó được ưu tiên thấp
          hơn cho shop của bạn, nhạt dần trong khoảng 60 ngày. Juli không chép lựa chọn của shop này sang shop
          khác.
        </P>
        <H3>Học giữa các shop: chỉ khi có bằng chứng</H3>
        <P>
          Học từ nhiều shop sẽ giúp những shop mới hay shop nhỏ có điểm xuất phát tốt hơn. Nhưng một kết luận
          chung chỉ được dùng khi nó đứng vững: hướng tác động giống nhau khi bỏ lần lượt từng shop ra, và
          khoảng tin cậy không chứa 0. Hiện chưa có loại thay đổi nào đạt chuẩn này, nên Juli không đưa ra
          con số hiệu quả chung nào, trên trang này hay trong ứng dụng. Kết quả đo chỉ dùng số liệu tổng hợp
          của sản phẩm, không dùng dữ liệu cá nhân của người mua.
        </P>
        <P>
          Muốn hiểu thêm về cách đọc chỉ số và dao động, xem các bài trên <A href={BLOG_PATH}>blog</A>.
        </P>
        <Note>
          Ảnh trên trang này lấy từ bản demo của Juli với “Cửa hàng Mẫu Hoa Mai”, một shop minh hoạ. Các
          con số là dữ liệu mẫu, không phải kết quả của một shop thật.
        </Note>
      </CapSection>
    </CapabilityPage>
  );
}
