import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import {
  Form,
  FormActions,
  FormError,
  FormField,
  FormInput,
  FormLabel,
  FormSubmit,
  OtpField,
  PasswordField,
  TextField,
} from "../form";
import { loadUiStyles, loadUiStyleRules } from "./test-utils";

const styles = loadUiStyles();
const styleRules = loadUiStyleRules();

describe("Form", () => {
  it("renders TextField with a linked label and Vietnamese copy", () => {
    render(
      <Form aria-label="Đăng nhập">
        <TextField
          autoComplete="email"
          id="email"
          label="Email"
          name="email"
          type="email"
        />
      </Form>,
    );

    const input = screen.getByLabelText("Email");

    expect(input).toHaveAttribute("id", "email");
    expect(input).toHaveClass("juli-form__input");
    expect(input).toHaveAttribute("type", "email");
  });

  it("links inline errors via aria-describedby", () => {
    render(
      <TextField
        errorMessage="Email không hợp lệ. Vui lòng kiểm tra lại định dạng."
        id="email-error"
        label="Email"
      />,
    );

    const input = screen.getByLabelText("Email");

    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(input).toHaveAttribute("aria-describedby", "email-error-error");
    expect(
      screen.getByText("Email không hợp lệ. Vui lòng kiểm tra lại định dạng."),
    ).toHaveAttribute("role", "alert");
  });

  it("marks required fields with an accessible asterisk", () => {
    render(<TextField id="shop-name" label="Tên cửa hàng" required />);

    expect(screen.getByText("Tên cửa hàng")).toHaveTextContent("*");
    expect(screen.getByRole("textbox", { name: /Tên cửa hàng/ })).toBeRequired();
  });

  it("toggles password visibility with Vietnamese aria labels", async () => {
    const user = userEvent.setup();

    render(<PasswordField id="password" label="Mật khẩu" />);

    const input = screen.getByLabelText("Mật khẩu");
    const toggle = screen.getByTestId("password-toggle-password");

    expect(input).toHaveAttribute("type", "password");
    expect(toggle).toHaveAttribute("aria-label", "Hiện mật khẩu");

    await user.click(toggle);

    expect(input).toHaveAttribute("type", "text");
    expect(toggle).toHaveAttribute("aria-label", "Ẩn mật khẩu");
  });

  it("auto-advances OTP digits and submits on the sixth digit", async () => {
    const user = userEvent.setup();
    const onComplete = vi.fn();

    function OtpFixture() {
      const [value, setValue] = useState("");

      return (
        <OtpField
          id="otp"
          onChange={setValue}
          onComplete={onComplete}
          value={value}
        />
      );
    }

    render(<OtpFixture />);

    for (let index = 0; index < 6; index += 1) {
      await user.type(screen.getByTestId(`otp-digit-${index}`), String(index + 1));
    }

    expect(onComplete).toHaveBeenCalledWith("123456");
  });

  it("shows OTP error copy with recovery guidance", () => {
    render(
      <OtpField
        errorMessage="Mã OTP không đúng. Vui lòng thử lại."
        id="otp-error"
        value=""
      />,
    );

    expect(
      screen.getByText("Mã OTP không đúng. Vui lòng thử lại."),
    ).toHaveAttribute("role", "alert");
    expect(screen.getByRole("group")).toHaveClass("juli-form__otp--error");
  });

  it("navigates OTP digits with arrow keys", async () => {
    const user = userEvent.setup();

    render(<OtpField id="otp-nav" value="" />);

    const first = screen.getByTestId("otp-digit-0");
    const second = screen.getByTestId("otp-digit-1");

    first.focus();
    await user.keyboard("{ArrowRight}");

    expect(second).toHaveFocus();
  });

  it("composes FormSubmit from the shared Button primitive", () => {
    render(
      <Form>
        <FormActions>
          <FormSubmit disabled loading>
            Đang lưu
          </FormSubmit>
        </FormActions>
      </Form>,
    );

    const submit = screen.getByRole("button", { name: "Đang lưu" });

    expect(submit).toHaveClass("juli-btn", "juli-btn--primary");
    expect(submit).toBeDisabled();
    expect(submit).toHaveAttribute("type", "submit");
  });

  it("documents 44px inputs, focus-visible, and error states in CSS", () => {
    expect(styles).toContain(".juli-form__input");
    expect(styles).toContain("min-height: var(--juli-touch-target)");
    expect(styles).toContain(".juli-form__input:focus-visible");
    expect(styles).toContain(".juli-form__input--error");
    expect(styles).toContain(".juli-form__otp-digit");
    expect(styles).toContain(".juli-form__password-toggle:focus-visible");
    expect(styleRules).not.toMatch(/#[0-9a-f]{3,8}/i);
  });

  it("exposes labelled primitives for custom field layouts", () => {
    render(
      <FormField data-testid="custom-field">
        <FormLabel htmlFor="notes">Ghi chú</FormLabel>
        <FormInput id="notes" name="notes" />
        <FormError id="notes-error">Vui lòng nhập ghi chú trước khi lưu.</FormError>
      </FormField>,
    );

    expect(screen.getByLabelText("Ghi chú")).toHaveAttribute("id", "notes");
    expect(screen.getByTestId("custom-field")).toBeInTheDocument();
  });
});
