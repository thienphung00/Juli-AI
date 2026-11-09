import { fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import type { PickerProduct } from "../../../lib/shopee-decisions/builder-api";
import { P_GLOVE, P_ZIP, pickerProducts } from "../../../lib/shopee-decisions/__tests__/builder-fixtures";
import { TablePicker } from "../builder-p92/table-picker";

function many(): PickerProduct[] {
  const base = pickerProducts().products;
  const extra = Array.from({ length: 40 }, (_, i): PickerProduct => ({ ...base[5]!, item_id: `7000${String(i).padStart(2, "0")}`, name: `Nước rửa tay mẫu ${i + 1}`, category: "Nước rửa tay", margin_pct: 20 }));
  return [...base.slice(0, 5), ...extra];
}

function Harness({ products, max }: { readonly products: PickerProduct[]; readonly max?: number }) {
  const [sel, setSel] = useState<readonly string[]>([]);
  return <TablePicker max={max} mode="multi" onChange={setSel} products={products} selected={sel} />;
}

describe("P97 D85.12 · TablePicker", () => {
  it("picks 30+ products by one category filter and one click of 'chọn tất cả theo bộ lọc'", () => {
    render(<Harness products={many()} />);
    fireEvent.change(screen.getByLabelText("Ngành hàng"), { target: { value: "Nước rửa tay" } });
    fireEvent.click(screen.getByTestId("p2-select-filtered"));
    expect(screen.getByTestId("p2-sel-count")).toHaveTextContent("Đã chọn 40 sản phẩm");
  });

  it("a ticked row, a pasted list and × all edit the same selection list", () => {
    render(<Harness products={many()} />);
    fireEvent.click(screen.getByRole("checkbox", { name: /Chọn Túi zip thực phẩm D/ }));
    expect(screen.getByTestId("p2-sel-count")).toHaveTextContent("Đã chọn 1 sản phẩm");
    fireEvent.click(screen.getByText("Dán danh sách mã sản phẩm"));
    fireEvent.change(screen.getByLabelText("Dán danh sách mã sản phẩm", { selector: "textarea" }), { target: { value: `${P_GLOVE}, 700001\n404` } });
    fireEvent.click(screen.getByTestId("p2-paste-go"));
    expect(screen.getByTestId("p2-paste-note")).toHaveTextContent("Đã chọn 2 mã; 1 mã không tìm thấy hoặc không chọn được: 404");
    expect(screen.getByTestId("p2-sel-count")).toHaveTextContent("Đã chọn 3 sản phẩm");
    const list = screen.getByTestId("p2-sel");
    fireEvent.click(within(list).getByRole("button", { name: `Bỏ Túi zip thực phẩm D` }));
    expect(screen.getByTestId("p2-sel-count")).toHaveTextContent("Đã chọn 2 sản phẩm");
    expect(screen.getByRole("checkbox", { name: /Chọn Túi zip thực phẩm D/ })).not.toBeChecked();
    fireEvent.click(screen.getByRole("button", { name: "Bỏ chọn hết" }));
    expect(screen.getByTestId("p2-sel-count")).toHaveTextContent("Đã chọn 0 sản phẩm");
  });

  it("the cap stops the selection and says so", () => {
    render(<Harness max={3} products={many()} />);
    fireEvent.click(screen.getByTestId("p2-select-filtered"));
    expect(screen.getByTestId("p2-sel-count")).toHaveTextContent("Đã chọn 3 sản phẩm (tối đa 3)");
  });

  it("filter chips narrow the rows and 'Bỏ bộ lọc' restores them", () => {
    render(<Harness products={many()} />);
    fireEvent.click(screen.getByRole("button", { name: "CTOR giảm 1" }));
    expect(screen.getAllByTestId(/^p2-prod-/)).toHaveLength(1);
    expect(screen.getByTestId(`p2-prod-${P_GLOVE}`)).toHaveTextContent("có đề xuất");
    fireEvent.click(screen.getByRole("button", { name: "Bỏ bộ lọc" }));
    expect(screen.queryByRole("button", { name: "Bỏ bộ lọc" })).toBeNull();
    expect(screen.getByTestId(`p2-prod-${P_ZIP}`)).toBeInTheDocument();
  });

  it("disabled ids cannot be ticked", () => {
    const products = many();
    render(<TablePicker disabled={[P_ZIP]} mode="multi" onChange={() => {}} products={products} selected={[]} />);
    expect(screen.getByRole("checkbox", { name: /Chọn Túi zip thực phẩm D/ })).toBeDisabled();
  });
});
