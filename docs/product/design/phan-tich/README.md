# Phân tích — streams, metrics, rankings → Đề xuất (ADR-109 Amendment 2)

Owner-approved design, 2026-10-09. Source canvas "Thiết kế UI flow":
https://claude.ai/artifact/14dAfWFM16ZznYTeQRsGj8 (copied here as `.dc.html` artboards).
**The UI must match these artboards exactly**: copy, order, colours, spacing, radii, font
sizes, states. Each `.dc.html` is HTML with inline styles plus a `renderVals()` script
that drives every state; read both.

| Artboard | What it is | Where it lives in the app |
|---|---|---|
| `PtProduct.dc.html` | Sản phẩm: header, Juli gợi ý, stream cards (Thẻ sản phẩm, Tab cửa hàng), cells, ranking, row detail, Còn lại, Khuyến mãi, Lịch sale và chiến dịch | Phân tích › Sản phẩm |
| `PtContent.dc.html` | Nội dung: Video and LIVE streams, video/LIVE rows, greyed "Phụ thuộc sản phẩm" cells | Phân tích › Nội dung |
| `PtMobile.dc.html` | Sản phẩm at 390 px | Phân tích, mobile |
| `PtFlow.dc.html` | Phân tích → Đề xuất → Phân tích links (incl. "Xem phân tích ›" on the card, highlight on arrival) | Reference + the card link |
| `LinkA.dc.html` | The caption line under the sub-tabs (Liên kết = option A) | Both sub-tabs |

Numbers in the artboards are illustrative (a cosmetics sample shop); real values come
from the shop-diagnosis report and metric rankings (ADR-108, ADR-109 decision 5).
