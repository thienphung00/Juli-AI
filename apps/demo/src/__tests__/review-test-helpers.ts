import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

export async function confirmApproveThroughGate(
  user: ReturnType<typeof userEvent.setup>,
) {
  await user.click(screen.getByRole("button", { name: "Phê duyệt" }));
  const dialog = await screen.findByRole("dialog");
  await user.click(within(dialog).getByRole("button", { name: "Phê duyệt" }));
}

// A minimal well-formed PNG: signature plus an IHDR chunk — enough to pass
// the upload control's signature check (the same bytes the @juli/ui
// file-upload-field tests use).
const VALID_PNG_BYTES = new Uint8Array([
  0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, // PNG signature
  0x00, 0x00, 0x00, 0x0d, // IHDR chunk size
  0x49, 0x48, 0x44, 0x52, // IHDR chunk type
  0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x01, // width, height
  0x08, 0x02, 0x00, 0x00, 0x00, 0x90, 0x77, 0x53, // bit depth, color, etc.
]);

export function makeValidPngFile(name = "product.png"): File {
  return new File([VALID_PNG_BYTES], name, { type: "image/png" });
}

/**
 * Simulate picking a file in a `type="file"` input — jsdom has no real file
 * picker, so the `files` list is defined directly and a bubbling `change`
 * event is dispatched (the established pattern from
 * `packages/ui/src/__tests__/file-upload-field.test.tsx`). The upload
 * control's checks run asynchronously; callers must `waitFor` the effect
 * they expect.
 */
export function selectUploadFile(input: HTMLElement, file: File): void {
  Object.defineProperty(input, "files", {
    value: [file],
    writable: false,
  });
  input.dispatchEvent(new Event("change", { bubbles: true }));
}
