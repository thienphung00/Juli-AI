# Quyết định — card and flows (ADR-109 Amendment 1)

Owner-approved design, 2026-10-09. Source canvas:
https://claude.ai/artifact/14dAfWFM16ZznYTeQRsGj8 (copied here as `.dc.html` artboards).
**The UI must match these artboards exactly**: copy, order, colours, spacing, radii,
font sizes, states. Each `.dc.html` is HTML with inline styles plus a small
`renderVals()` script that shows every state; read both.

| Artboard | What it is | Where it lives in the app |
|---|---|---|
| `Main.dc.html` | Recommendation card, collapsed / Xem thêm / approved / rejected | Quyết định › Đề xuất |
| `Mobile.dc.html` | The card at 390 px | Đề xuất, mobile |
| `Levers.dc.html` | The 7 change types and who executes each | Đề xuất (card variants) |
| `Flow.dc.html` | Overview of the 8 steps + branches | Reference only (not a screen) |
| `Run.dc.html` | Đang thực hiện: title/description run, consent with edit, queue | Quyết định › Đang thực hiện |
| `RunPhoto.dc.html` | Đang thực hiện: cover image (photo request, check, consent, upload) | Đang thực hiện |
| `RunManual.dc.html` | Đang thực hiện: promotions on Seller Center (checklist, "Tôi đã áp dụng", verify) | Đang thực hiện |
| `Measure.dc.html` | Đo lường: target + allowed band, tabs Ngày 0 / 7 / 14, collapse | Quyết định › Đo lường |
| `Day7.dc.html` | Day-7 check flow (within band / outside → Hoàn tác?) | Đo lường |
| `Day14.dc.html` | Day-14 final (Đạt / Gần đạt / Không đạt / Chưa kết luận) | Đo lường |
| `Revert.dc.html` | Hoàn tác: reason dialog (one required), conflict branch, consent, restore | Dialog + Đang thực hiện |
| `Decline.dc.html` | Từ chối (Đề xuất) and Không thực hiện (consent) with reason dialog | Dialogs |

Demo-only affordances in the artboards that are NOT product features: the "Ví dụ" /
scenario switches, "Mô phỏng: chạy tiếp", "↺ Xem lại từ đầu". Real state comes from the
API and the run's SSE stream. Numbers in the artboards are illustrative.

API contract between backend and UI: `fasttrack/contracts/p10-quyet-dinh.md`.
