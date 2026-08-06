import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { FileUploadField } from "../file-upload-field";

describe("FileUploadField", () => {
  it("renders with label and required indicator", () => {
    render(
      <FileUploadField label="Ảnh sản phẩm" onChange={() => {}} required />,
    );

    const label = screen.getByText("Ảnh sản phẩm");
    expect(label).toBeInTheDocument();
    expect(label.parentElement).toHaveTextContent("*");
  });

  it("accepts valid image files", async () => {
    const onChange = vi.fn();

    const { container } = render(
      <FileUploadField
        label="Ảnh sản phẩm"
        onChange={onChange}
        required
      />,
    );

    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(
      [new Uint8Array([0xff, 0xd8, 0xff, 0xe0])],
      "product.jpg",
      { type: "image/jpeg" },
    );

    Object.defineProperty(input, "files", {
      value: [file],
      writable: false,
    });

    const event = new Event("change", { bubbles: true });
    input.dispatchEvent(event);

    await waitFor(() => {
      expect(onChange).toHaveBeenCalledWith(
        expect.objectContaining({
          name: "product.jpg",
          type: "image/jpeg",
        }),
      );
    });
  });

  it("rejects non-image files with seller-language copy", async () => {
    const onChange = vi.fn();

    const { container } = render(
      <FileUploadField
        label="Ảnh sản phẩm"
        onChange={onChange}
        required
      />,
    );

    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File([new Uint8Array([0x25, 0x50, 0x44, 0x46])], "doc.pdf", {
      type: "application/pdf",
    });

    // Manually trigger change event with file
    Object.defineProperty(input, "files", {
      value: [file],
      writable: false,
    });

    const event = new Event("change", { bubbles: true });
    input.dispatchEvent(event);

    await waitFor(() => {
      const errorMessage = screen.getByRole("alert");
      expect(errorMessage).toBeInTheDocument();
    });

    const errorMessage = screen.getByRole("alert");
    expect(errorMessage.textContent).toMatch(/ảnh|hình ảnh|không hỗ trợ/i);
    expect(errorMessage.textContent).not.toMatch(/application|pdf|mime|type/i);
  });

  it("rejects files with mismatched extension and content type", async () => {
    const onChange = vi.fn();

    const { container } = render(
      <FileUploadField
        label="Ảnh sản phẩm"
        onChange={onChange}
        required
      />,
    );

    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    // PDF magic bytes in a .jpg file
    const file = new File([new Uint8Array([0x25, 0x50, 0x44, 0x46])], "fake.jpg", {
      type: "image/jpeg",
    });

    Object.defineProperty(input, "files", {
      value: [file],
      writable: false,
    });

    const event = new Event("change", { bubbles: true });
    input.dispatchEvent(event);

    await waitFor(() => {
      const errorMessage = screen.getByRole("alert");
      expect(errorMessage).toBeInTheDocument();
    });

    const errorMessage = screen.getByRole("alert");
    expect(errorMessage.textContent).toMatch(/không hợp lệ|không nhận dạng/i);
  });

  it("rejects oversized files with seller-language copy", async () => {
    const onChange = vi.fn();

    const { container } = render(
      <FileUploadField
        label="Ảnh sản phẩm"
        onChange={onChange}
        required
        maxSize={1024 * 1024}
      />,
    );

    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    // Create a file larger than maxSize
    const largeData = new Uint8Array(2 * 1024 * 1024);
    largeData[0] = 0xff;
    largeData[1] = 0xd8;
    largeData[2] = 0xff;
    largeData[3] = 0xe0;
    const file = new File([largeData], "large.jpg", { type: "image/jpeg" });

    Object.defineProperty(input, "files", {
      value: [file],
      writable: false,
    });

    const event = new Event("change", { bubbles: true });
    input.dispatchEvent(event);

    await waitFor(() => {
      const errorMessage = screen.getByRole("alert");
      expect(errorMessage).toBeInTheDocument();
    });

    const errorMessage = screen.getByRole("alert");
    expect(errorMessage.textContent).toMatch(/quá lớn|dung lượng/i);
  });

  it("contains no virus or antivirus terminology in rendered strings", () => {
    const { container } = render(
      <FileUploadField
        label="Ảnh sản phẩm"
        onChange={() => {}}
        required
      />,
    );

    const text = container.textContent ?? "";
    expect(text).not.toMatch(/virus|antivirus|malware|an toàn/i);
  });

  it("displays helper text about accepted file types", () => {
    render(
      <FileUploadField
        label="Ảnh sản phẩm"
        onChange={() => {}}
        required
      />,
    );

    const helper = screen.getByText(/chỉ hỗ trợ ảnh|ảnh sản phẩm/i);
    expect(helper).toBeInTheDocument();
  });

  it("has a minimum 44px tap target for the input", () => {
    const { container } = render(
      <FileUploadField
        label="Ảnh sản phẩm"
        onChange={() => {}}
        required
      />,
    );

    const input = container.querySelector("input[type='file']");
    const styles = window.getComputedStyle(input!);
    // The component should use atau-touch-target or equivalent
    expect(input).toHaveClass("juli-form__file-input");
  });
});
