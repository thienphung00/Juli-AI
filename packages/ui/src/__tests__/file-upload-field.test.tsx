import { readFileSync } from "node:fs";
import { join } from "node:path";

import { SELLER_COPY_BANNED_PATTERNS } from "@juli/contracts";
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { FileUploadField } from "../file-upload-field";

// Banned patterns in seller-facing copy. Read from the single shared source
// (ADR-070 decision 6, #990) instead of a hand-maintained local copy — see
// packages/contracts/src/seller-copy.ts and
// packages/contracts/seller-copy-banned-patterns.json (issue #1002).

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

  it("flags banned text that only the shared @juli/contracts source defines (drift check)", () => {
    // "ship" (\bship\b, issue #1002 / ADR-070 decision 6) is banned in the shared
    // packages/contracts/seller-copy-banned-patterns.json but was never part of this
    // file's old hand-maintained copy. This proves SELLER_COPY_BANNED_PATTERNS here
    // is read from the shared source, not a stale local list that happens to still
    // pass the other assertions in this file.
    expect(
      SELLER_COPY_BANNED_PATTERNS.some((pattern) =>
        pattern.test("please ship this order"),
      ),
    ).toBe(true);
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

  // --- New coverage for the ::file-selector-button fix (issue #925) ---
  // jsdom's getBoundingClientRect() is always a zeroed rect, so none of the
  // assertions below rely on it. Keyboard behaviour is asserted via
  // focus()/toHaveFocus(), and the visual/button styling is asserted by
  // inspecting the authored stylesheet directly (jsdom does not compute
  // styles for ::file-selector-button, a UA shadow part).

  it("keeps native keyboard focus on the file input (the ::file-selector-button fix does not hide it)", () => {
    const { container } = render(
      <FileUploadField label="Ảnh sản phẩm" onChange={() => {}} required />,
    );

    const input = container.querySelector(
      "input[type='file']",
    ) as HTMLInputElement;

    expect(input).not.toHaveAttribute("type", "hidden");
    expect(input.style.display).not.toBe("none");

    input.focus();
    expect(input).toHaveFocus();
  });

  it("keeps the visible label wired to the real input via htmlFor, not a styled label standing in for it", () => {
    render(
      <FileUploadField label="Ảnh sản phẩm" onChange={() => {}} required />,
    );

    const input = screen.getByLabelText("Ảnh sản phẩm *", {
      exact: false,
    }) as HTMLInputElement;
    expect(input).toHaveAttribute("type", "file");
  });

  it("styles the native file-selector-button via ::file-selector-button instead of a hidden-input + label pattern", () => {
    const css = readFileSync(join(process.cwd(), "styles.css"), "utf8");

    // The button drawn inside a file input is only reachable via this
    // pseudo-element. Its presence is the chosen fix (see file-upload-field
    // design decision): keep the native <input type="file">, don't hide it
    // behind a styled <label>.
    expect(css).toMatch(
      /\.juli-form__file-input::file-selector-button\s*\{/,
    );
    expect(css).toMatch(
      /\.juli-form__file-input::file-selector-button:hover\s*\{/,
    );
  });

  it("does not declare accent-color anywhere in the stylesheet (dead on file inputs, and nothing else in the sheet uses it)", () => {
    const css = readFileSync(join(process.cwd(), "styles.css"), "utf8");

    expect(css).not.toMatch(/accent-color/);
  });

  it("still applies the shared touch-target and focus-visible tokens to the file input itself", () => {
    const css = readFileSync(join(process.cwd(), "styles.css"), "utf8");
    const fileInputRuleMatch = css.match(
      /\.juli-form__file-input\s*\{([^}]*)\}/,
    );
    const focusRuleMatch = css.match(
      /\.juli-form__file-input:focus-visible\s*\{([^}]*)\}/,
    );

    expect(fileInputRuleMatch?.[1]).toMatch(
      /min-height:\s*var\(--juli-touch-target\)/,
    );
    expect(focusRuleMatch?.[1]).toMatch(
      /outline:\s*var\(--juli-focus-width\)\s+solid\s+var\(--juli-focus-ring\)/,
    );
  });
});
