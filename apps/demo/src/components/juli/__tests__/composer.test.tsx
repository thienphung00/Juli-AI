import { readFileSync } from "node:fs";
import { join } from "node:path";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createRef } from "react";
import { describe, expect, it, vi } from "vitest";

import { Composer, MAX_QUESTION_CHARS } from "../composer";

function setup(over: { running?: boolean; disabled?: boolean } = {}) {
  const onSubmit = vi.fn();
  const onStop = vi.fn();
  const inputRef = createRef<HTMLTextAreaElement>();
  render(<Composer running={over.running ?? false} disabled={over.disabled ?? false} inputRef={inputRef} onSubmit={onSubmit} onStop={onStop} />);
  const field = screen.getByRole("textbox") as HTMLTextAreaElement;
  return { onSubmit, onStop, inputRef, field };
}

describe("C1 Enter / Shift+Enter / IME", () => {
  it("is a one-row textarea", () => {
    const { field } = setup();
    expect(field.tagName).toBe("TEXTAREA");
    expect(field.rows).toBe(1);
  });
  it("Enter sends the trimmed text and clears the field", async () => {
    const { field, onSubmit } = setup();
    await userEvent.type(field, "  doanh thu hôm nay  {Enter}");
    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(onSubmit).toHaveBeenCalledWith("doanh thu hôm nay");
    expect(field.value).toBe("");
  });
  it("Shift+Enter adds a line and does not send", async () => {
    const { field, onSubmit } = setup();
    await userEvent.type(field, "dòng một{Shift>}{Enter}{/Shift}dòng hai");
    expect(onSubmit).not.toHaveBeenCalled();
    expect(field.value).toBe("dòng một\ndòng hai");
    await userEvent.keyboard("{Enter}");
    expect(onSubmit).toHaveBeenCalledWith("dòng một\ndòng hai");
  });
  it("Enter during an IME composition does not send (isComposing)", () => {
    const { field, onSubmit } = setup();
    fireEvent.change(field, { target: { value: "xin chao" } });
    const notPrevented = fireEvent.keyDown(field, { key: "Enter", isComposing: true });
    expect(onSubmit).not.toHaveBeenCalled();
    expect(notPrevented).toBe(true); // the IME keeps its Enter
    expect(field.value).toBe("xin chao");
  });
  it("Enter with keyCode 229 does not send (Safari order)", () => {
    const { field, onSubmit } = setup();
    fireEvent.change(field, { target: { value: "xin chao" } });
    fireEvent.keyDown(field, { key: "Enter", keyCode: 229 });
    expect(onSubmit).not.toHaveBeenCalled();
    fireEvent.keyDown(field, { key: "Enter", keyCode: 13 });
    expect(onSubmit).toHaveBeenCalledWith("xin chao");
  });
  it("an empty or blank text never sends", async () => {
    const { field, onSubmit } = setup();
    await userEvent.type(field, "   {Enter}");
    expect(onSubmit).not.toHaveBeenCalled();
  });
  it("the send button still submits", async () => {
    const { field, onSubmit } = setup();
    await userEvent.type(field, "hello");
    await userEvent.click(screen.getByRole("button", { name: "Gửi" }));
    expect(onSubmit).toHaveBeenCalledWith("hello");
  });
});

describe("C2 auto-grow and line breaks", () => {
  it("sets the height from the content and resets it after sending", () => {
    const { field } = setup();
    Object.defineProperty(field, "scrollHeight", { configurable: true, value: 88 });
    fireEvent.change(field, { target: { value: "a\nb\nc\nd" } });
    expect(field.style.height).toBe("88px");
    fireEvent.keyDown(field, { key: "Enter", keyCode: 13 });
    expect(field.style.height).toBe("");
  });
  it("css: capped height with scroll, one-line minimum, bubble keeps line breaks", () => {
    const css = readFileSync(join(__dirname, "../../../app/juli/juli.css"), "utf8");
    const field = css.match(/\.juli-input__field \{[^}]*\}/)![0];
    expect(field).toContain("max-height: 160px");
    expect(field).toContain("overflow-y: auto");
    expect(field).toContain("min-height: 44px");
    expect(field).toContain("resize: none");
    expect(css.match(/\.juli-me \{[^}]*\}/)![0]).toContain("white-space: pre-wrap");
  });
});

describe("C3 text limit", () => {
  it("allows 2000 characters, as the API does", () => {
    const { field } = setup();
    expect(MAX_QUESTION_CHARS).toBe(2000);
    expect(field.maxLength).toBe(2000);
  });
  it("sends a long pasted text whole", async () => {
    const { field, onSubmit } = setup();
    const long = "x".repeat(1800);
    await userEvent.click(field);
    await userEvent.paste(long);
    await userEvent.keyboard("{Enter}");
    expect(onSubmit).toHaveBeenCalledWith(long);
  });
});

describe("C4 states unchanged", () => {
  it("disabled: the field is off and nothing sends", () => {
    const { field, onSubmit } = setup({ disabled: true });
    expect(field.disabled).toBe(true);
    fireEvent.keyDown(field, { key: "Enter", keyCode: 13 });
    expect(onSubmit).not.toHaveBeenCalled();
    expect(document.querySelector(".juli-input--off")).not.toBeNull();
  });
  it("running: shows Dừng, the stop button stops, Enter does not send", async () => {
    const { field, onSubmit, onStop } = setup({ running: true });
    expect(field.placeholder).toBe("Bạn có thể gõ câu tiếp theo…");
    await userEvent.type(field, "câu tiếp{Enter}");
    expect(onSubmit).not.toHaveBeenCalled();
    expect(field.value).toBe("câu tiếp");
    await userEvent.click(screen.getByRole("button", { name: /Dừng/ }));
    expect(onStop).toHaveBeenCalledTimes(1);
    expect((screen.getByRole("button", { name: "Gửi" }) as HTMLButtonElement).disabled).toBe(true);
  });
  it("the ref points at the textarea so onOther can focus it", () => {
    const { inputRef, field } = setup();
    inputRef.current?.focus();
    expect(document.activeElement).toBe(field);
  });
  it("not running: no stop button", () => {
    setup();
    expect(screen.queryByRole("button", { name: /Dừng/ })).toBeNull();
  });
});
