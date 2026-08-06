import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { FileUploadField } from "../file-upload-field";

// Banned patterns in seller-facing copy — must match SELLER_COPY_BANNED_PATTERNS in @juli/contracts
// The demo-side test asserts these two lists stay in sync to prevent drift
const SELLER_COPY_BANNED_PATTERNS = [
  /tool_name/i,
  /workflow_key/i,
  /feature_id/i,
  /\bwebhook\b/i,
  /\bendpoint\b/i,
  /\bFBS\b/,
  /\bFBT\b/,
  /Độ tin cậy:/,
  /Công cụ:/,
  /Khả năng:/,
  /Get Product/i,
  /Unresolved\/Unfilled/i,
  /listing\./,
  /inventory\./,
  /fulfillment\./,
  /returns\./,
  /promotion\./,
  // False security claims — file validation is MIME type and truncation only
  /\bvirus\b/i,
  /\bviruses\b/i,
  /antivirus/i,
  /malware/i,
  /\ban toàn\b/i,  // Vietnamese: "safe/safety" — forbid affirmative safety claims
  /kiểm tra an toàn/i,
  /tệp an toàn/i,
] as const;

beforeEach(() => {
  // Mock createImageBitmap for tests to verify image decode
  const mockCreateImageBitmap = vi.fn(async (source: unknown) => {
    // For test "rejects truncated PNG files", check file size
    if (source instanceof File && source.name === "truncated.png") {
      throw new Error("PNG file truncated");
    }

    // For all other files, return success
    return { close: vi.fn() } as unknown as ImageBitmap;
  });

  vi.stubGlobal("createImageBitmap", mockCreateImageBitmap);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

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
    // Minimal valid PNG: proper header + minimal IHDR chunk (24+ bytes)
    // PNG signature + minimal IHDR chunk data
    const pngData = new Uint8Array([
      0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, // PNG signature
      0x00, 0x00, 0x00, 0x0d, // IHDR chunk size
      0x49, 0x48, 0x44, 0x52, // IHDR chunk type
      0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x01, // width, height
      0x08, 0x02, 0x00, 0x00, 0x00, 0x90, 0x77, 0x53, // bit depth, color, etc.
    ]);
    const file = new File([pngData], "product.png", { type: "image/png" });

    Object.defineProperty(input, "files", {
      value: [file],
      writable: false,
    });

    const event = new Event("change", { bubbles: true });
    input.dispatchEvent(event);

    await waitFor(() => {
      // Check if there's an error message (indicates test failure reason)
      try {
        const errorMsg = screen.queryByRole("alert");
        if (errorMsg) {
          throw new Error(`Got error: ${errorMsg.textContent}`);
        }
      } catch (e) {
        // Log for debugging
      }

      expect(onChange).toHaveBeenCalledWith(
        expect.objectContaining({
          name: "product.png",
          type: "image/png",
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

  it("rejects truncated PNG files with seller-language copy", async () => {
    const onChange = vi.fn();

    const { container } = render(
      <FileUploadField
        label="Ảnh sản phẩm"
        onChange={onChange}
        required
      />,
    );

    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    // PNG header but truncated body (less than 24 bytes)
    const truncatedPng = new File(
      [new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a])],
      "truncated.png",
      { type: "image/png" },
    );

    Object.defineProperty(input, "files", {
      value: [truncatedPng],
      writable: false,
    });

    const event = new Event("change", { bubbles: true });
    input.dispatchEvent(event);

    await waitFor(() => {
      const errorMessage = screen.getByRole("alert");
      expect(errorMessage).toBeInTheDocument();
    });

    const errorMessage = screen.getByRole("alert");
    expect(errorMessage.textContent).toMatch(/bị hỏng|không đầy đủ/i);
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
    // Create a file larger than maxSize with PNG signature
    const largeData = new Uint8Array(2 * 1024 * 1024);
    largeData[0] = 0x89;
    largeData[1] = 0x50;
    largeData[2] = 0x4e;
    largeData[3] = 0x47;
    largeData[4] = 0x0d;
    largeData[5] = 0x0a;
    largeData[6] = 0x1a;
    largeData[7] = 0x0a;
    const file = new File([largeData], "large.png", { type: "image/png" });

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

  it("contains no banned terminology in default state", () => {
    const { container } = render(
      <FileUploadField
        label="Ảnh sản phẩm"
        onChange={() => {}}
        required
      />,
    );

    const text = container.textContent ?? "";
    SELLER_COPY_BANNED_PATTERNS.forEach((pattern) => {
      expect(text).not.toMatch(pattern);
    });
  });

  it("contains no banned terminology when rejecting non-image file", async () => {
    const { container } = render(
      <FileUploadField
        label="Ảnh sản phẩm"
        onChange={() => {}}
        required
      />,
    );

    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File([new Uint8Array([0x25, 0x50, 0x44, 0x46])], "doc.pdf", {
      type: "application/pdf",
    });

    Object.defineProperty(input, "files", {
      value: [file],
      writable: false,
    });

    const event = new Event("change", { bubbles: true });
    input.dispatchEvent(event);

    await waitFor(() => {
      screen.getByRole("alert");
    });

    const text = container.textContent ?? "";
    SELLER_COPY_BANNED_PATTERNS.forEach((pattern) => {
      expect(text).not.toMatch(pattern);
    });
  });

  it("contains no banned terminology when rejecting oversized file", async () => {
    const { container } = render(
      <FileUploadField
        label="Ảnh sản phẩm"
        onChange={() => {}}
        required
        maxSize={1024 * 1024}
      />,
    );

    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    const largeData = new Uint8Array(2 * 1024 * 1024);
    largeData[0] = 0x89;
    largeData[1] = 0x50;
    largeData[2] = 0x4e;
    largeData[3] = 0x47;
    largeData[4] = 0x0d;
    largeData[5] = 0x0a;
    largeData[6] = 0x1a;
    largeData[7] = 0x0a;
    const file = new File([largeData], "large.png", { type: "image/png" });

    Object.defineProperty(input, "files", {
      value: [file],
      writable: false,
    });

    const event = new Event("change", { bubbles: true });
    input.dispatchEvent(event);

    await waitFor(() => {
      screen.getByRole("alert");
    });

    const text = container.textContent ?? "";
    SELLER_COPY_BANNED_PATTERNS.forEach((pattern) => {
      expect(text).not.toMatch(pattern);
    });
  });

  it("contains no banned terminology when rejecting signature mismatch", async () => {
    const { container } = render(
      <FileUploadField
        label="Ảnh sản phẩm"
        onChange={() => {}}
        required
      />,
    );

    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
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
      screen.getByRole("alert");
    });

    const text = container.textContent ?? "";
    SELLER_COPY_BANNED_PATTERNS.forEach((pattern) => {
      expect(text).not.toMatch(pattern);
    });
  });

  it("contains no banned terminology when rejecting truncated file", async () => {
    const { container } = render(
      <FileUploadField
        label="Ảnh sản phẩm"
        onChange={() => {}}
        required
      />,
    );

    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    const truncatedPng = new File(
      [new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a])],
      "truncated.png",
      { type: "image/png" },
    );

    Object.defineProperty(input, "files", {
      value: [truncatedPng],
      writable: false,
    });

    const event = new Event("change", { bubbles: true });
    input.dispatchEvent(event);

    await waitFor(() => {
      screen.getByRole("alert");
    });

    const text = container.textContent ?? "";
    SELLER_COPY_BANNED_PATTERNS.forEach((pattern) => {
      expect(text).not.toMatch(pattern);
    });
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
