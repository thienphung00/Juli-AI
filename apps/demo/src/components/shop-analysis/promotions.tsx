import type { Band, FlashAnalysis, VoucherSummary } from "../../lib/shop-analysis/types";
import { money, num, pct, shortDate } from "../../lib/vn-format";
import { ConfidenceBadge, Note, TableWrap } from "./shared";

/** Backend `render._bands_table`. */
export function BandsTable({ bands }: { readonly bands: Band[] }) {
  const rows = bands.filter((b) => b.kind !== "Flash sale");
  if (rows.length === 0) {
    return <Note>Không có giảm giá sản phẩm hay voucher nào trong 60 ngày.</Note>;
  }
  return (
    <TableWrap label="Giảm giá sản phẩm và voucher">
      <table className="analysis-table">
        <thead>
          <tr>
            <th scope="col">Loại</th>
            <th scope="col">Tên</th>
            <th scope="col">Từ</th>
            <th scope="col">Đến</th>
            <th scope="col">Số ngày trong 30 ngày trước</th>
            <th scope="col">Số ngày trong 30 ngày gần đây</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((b) => (
            <tr key={`${b.kind}-${b.title}-${b.first}`}>
              <th scope="row">{b.kind}</th>
              <td className="analysis-table__text">{b.title}</td>
              <td>{shortDate(b.first)}</td>
              <td>{shortDate(b.last)}</td>
              <td>{b.days_prior}</td>
              <td>{b.days_last}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </TableWrap>
  );
}

function flashCount(bands: Band[]): string {
  const flashes = bands.filter((b) => b.kind === "Flash sale");
  if (flashes.length === 0) return "Không có flash sale nào trong 60 ngày.";
  const prior = flashes.filter((b) => b.days_prior).length;
  const last = flashes.filter((b) => b.days_last).length;
  return `${flashes.length} đợt flash sale trong 60 ngày (${prior} đợt chạm 30 ngày trước, ${last} đợt chạm 30 ngày gần đây).`;
}

function Depth({ value }: { readonly value: number | null }) {
  if (value !== null && value < 0) {
    return <b>giá flash cao hơn giá đang giảm sẵn {pct(-value, 1)}</b>;
  }
  return <b>{pct(value, 1)}</b>;
}

/** Backend `render._flash_section`. */
export function FlashSection({
  flash,
  bands,
  shopLevel,
}: {
  readonly flash: FlashAnalysis;
  readonly bands: Band[];
  readonly shopLevel: boolean;
}) {
  return (
    <div className="analysis-subsection">
      <h4>Flash sale ({shopLevel ? "toàn shop" : "sản phẩm này"})</h4>
      <p>
        {flashCount(bands)} Thời gian có flash sale: {pct(flash.coverage_prior, 0)} của 30 ngày trước,{" "}
        {pct(flash.coverage_last, 0)} của 30 ngày gần đây (30 ngày trước: {flash.flash_days_prior} ngày
        flash; 30 ngày gần đây: {flash.flash_days_last} ngày flash). Độ sâu thật (giá flash so với giá
        đã giảm sẵn): <Depth value={flash.true_depth} />; so với giá niêm yết: {pct(flash.list_depth, 1)}.
      </p>
      <div className="analysis-tags">
        {flash.flags.length > 0 ? (
          flash.flags.map((flag) => (
            <span key={flag} className="badge badge-warning">
              {flag}
            </span>
          ))
        ) : (
          <span className="analysis-note">Không có cờ nào.</span>
        )}
      </div>
      {flash.unattributed ? (
        <Note>
          {flash.unattributed} đợt flash sale không có danh sách sản phẩm; các đợt này được tính là
          áp dụng cho mọi sản phẩm.
        </Note>
      ) : null}
      <div className="analysis-two-col">
        <TableWrap label="Thời gian có flash sale theo tuần">
          <table className="analysis-table">
            <thead>
              <tr>
                <th scope="col">Tuần</th>
                <th scope="col">Thời gian có flash sale</th>
              </tr>
            </thead>
            <tbody>
              {flash.weekly.map(([monday, share]) => (
                <tr key={monday}>
                  <th scope="row">tuần từ {shortDate(monday)}</th>
                  <td>{pct(share, 0)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableWrap>
        <TableWrap label="Nhóm ngày có và không có flash sale">
          <table className="analysis-table">
            <thead>
              <tr>
                <th scope="col">Nhóm ngày (Thẻ sản phẩm của người bán)</th>
                <th scope="col">Số ngày</th>
                <th scope="col">Đơn hàng SKU</th>
                <th scope="col">CTOR</th>
                <th scope="col">Đơn trên lượt thêm vào giỏ</th>
              </tr>
            </thead>
            <tbody>
              {flash.cells.map((cell) => (
                <tr key={cell.group}>
                  <th scope="row">{cell.group}</th>
                  <td>{cell.days}</td>
                  <td>{num(cell.sku_orders, 0)}</td>
                  {cell.sufficient ? (
                    <>
                      <td>{pct(cell.ctor)}</td>
                      <td>{pct(cell.orders_per_cart, 1)}</td>
                    </>
                  ) : (
                    <>
                      <td>
                        <ConfidenceBadge label="Chưa đủ dữ liệu" />
                      </td>
                      <td>
                        <ConfidenceBadge label="Chưa đủ dữ liệu" />
                      </td>
                    </>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </TableWrap>
      </div>
    </div>
  );
}

/** Backend `render._voucher_section`. */
export function VoucherSection({ summary }: { readonly summary: VoucherSummary | undefined }) {
  if (!summary || !summary.yardstick) {
    return (
      <div className="analysis-subsection">
        <h4>Voucher</h4>
        <Note>Không đủ đơn một món để phân loại voucher.</Note>
      </div>
    );
  }
  const stick = summary.yardstick;
  return (
    <div className="analysis-subsection">
      <h4>Voucher</h4>
      <p>
        Giá một món phổ biến (30 ngày gần đây): <b>{money(stick.common_price)}</b>, từ {stick.sample} đơn
        một món; 75 % đơn một món có giá trị từ {money(stick.closing_cut)} trở lên.
      </p>
      {summary.live.length > 0 && (
        <TableWrap label="Voucher đang chạy trong 60 ngày">
          <table className="analysis-table">
            <thead>
              <tr>
                <th scope="col">Voucher</th>
                <th scope="col">Loại</th>
                <th scope="col">Ngưỡng đơn</th>
                <th scope="col">Thời gian</th>
                <th scope="col">Mức giảm so với giá một món</th>
                <th scope="col">Đơn sát dưới ngưỡng</th>
                <th scope="col">Đơn đạt ngưỡng: trước → sau khi bắt đầu</th>
                <th scope="col">Số lượt dùng tối đa (ước tính)</th>
                <th scope="col">Ghi chú</th>
              </tr>
            </thead>
            <tbody>
              {summary.live.map((a) => (
                <tr key={`${a.voucher.title}-${a.first}`}>
                  <th scope="row">{a.voucher.title}</th>
                  <td className="analysis-table__text">
                    {a.voucher_class}
                    {a.specific_products ? " · Riêng sản phẩm" : ""}
                  </td>
                  <td>{a.voucher.threshold ? money(a.voucher.threshold) : "không có"}</td>
                  <td>
                    {shortDate(a.first)}–{shortDate(a.last)}
                  </td>
                  <td>{pct(a.discount_share, 1)}</td>
                  <td>{pct(a.near_threshold_share, 0)}</td>
                  <td>
                    {pct(a.above_before, 0)} → {pct(a.above_after, 0)}
                  </td>
                  <td>
                    {a.redemptions_upper} đơn · {money(a.cost_upper)}
                  </td>
                  <td className="analysis-table__text">
                    {a.overlaps_flash ? "chưa tách được khỏi flash sale" : ""}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableWrap>
      )}
      <Note>
        Dữ liệu đơn không cho biết đơn nào dùng voucher nào, nên số lượt dùng và chi phí là mức tối
        đa: mọi đơn đạt ngưỡng trong thời gian voucher chạy.
      </Note>
      {summary.older_by_month.length > 0 && (
        <TableWrap label="Voucher cũ hơn theo tháng">
          <table className="analysis-table">
            <thead>
              <tr>
                <th scope="col">Tháng bắt đầu</th>
                <th scope="col">Loại</th>
                <th scope="col">Số voucher</th>
              </tr>
            </thead>
            <tbody>
              {summary.older_by_month.map(([month, label, count]) => (
                <tr key={`${month}-${label}`}>
                  <th scope="row">{month}</th>
                  <td className="analysis-table__text">{label}</td>
                  <td>{count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableWrap>
      )}
    </div>
  );
}
