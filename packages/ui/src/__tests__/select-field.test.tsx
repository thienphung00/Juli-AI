import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { SelectField } from "../form";

describe("SelectField", () => {
  it("renders a label and select element with the provided options", () => {
    render(
      <SelectField
        label="Tiêu đề SEO"
        options={[
          { label: "Lựa chọn 1", value: "option1" },
          { label: "Lựa chọn 2", value: "option2" },
        ]}
        value="option1"
        onChange={() => {}}
      />,
    );

    expect(
      screen.getByRole("combobox", { name: "Tiêu đề SEO" }),
    ).toBeInTheDocument();
  });

  it("pre-selects the proposed value and displays suggestion badge when editable and value matches prefill", () => {
    render(
      <SelectField
        label="Tiêu đề SEO"
        options={[
          { label: "Lựa chọn 1", value: "option1" },
          { label: "Lựa chọn 2", value: "option2" },
        ]}
        value="option1"
        prefillValue="option1"
        suggestion={true}
        onChange={() => {}}
      />,
    );

    const selectElement = screen.getByRole("combobox", {
      name: "Tiêu đề SEO",
    });
    expect(selectElement).toHaveValue("option1");

    expect(screen.getByText("Gợi ý bởi Juli")).toBeInTheDocument();
  });

  it("allows selection of an alternative option", () => {
    const { rerender } = render(
      <SelectField
        label="Tiêu đề SEO"
        options={[
          { label: "Lựa chọn 1", value: "option1" },
          { label: "Lựa chọn 2", value: "option2" },
        ]}
        value="option1"
        onChange={() => {}}
      />,
    );

    let selectElement = screen.getByRole("combobox", {
      name: "Tiêu đề SEO",
    });
    expect(selectElement).toHaveValue("option1");

    rerender(
      <SelectField
        label="Tiêu đề SEO"
        options={[
          { label: "Lựa chọn 1", value: "option1" },
          { label: "Lựa chọn 2", value: "option2" },
        ]}
        value="option2"
        onChange={() => {}}
      />,
    );

    selectElement = screen.getByRole("combobox", {
      name: "Tiêu đề SEO",
    });
    expect(selectElement).toHaveValue("option2");
  });

  it("disables the select when disabled prop is true", () => {
    render(
      <SelectField
        label="Tiêu đề SEO"
        options={[
          { label: "Lựa chọn 1", value: "option1" },
          { label: "Lựa chọn 2", value: "option2" },
        ]}
        value="option1"
        disabled={true}
        onChange={() => {}}
      />,
    );

    expect(
      screen.getByRole("combobox", { name: "Tiêu đề SEO" }),
    ).toBeDisabled();
  });

  it("supports required field marker", () => {
    render(
      <SelectField
        label="Tiêu đề SEO"
        options={[
          { label: "Lựa chọn 1", value: "option1" },
          { label: "Lựa chọn 2", value: "option2" },
        ]}
        value="option1"
        required={true}
        onChange={() => {}}
      />,
    );

    expect(
      screen.getByRole("combobox", { name: "Tiêu đề SEO" }),
    ).toBeRequired();
  });

  it("displays helper text when provided", () => {
    render(
      <SelectField
        label="Tiêu đề SEO"
        options={[
          { label: "Lựa chọn 1", value: "option1" },
          { label: "Lựa chọn 2", value: "option2" },
        ]}
        value="option1"
        helperText="Chọn một tiêu đề được đề xuất"
        onChange={() => {}}
      />,
    );

    expect(
      screen.getByText("Chọn một tiêu đề được đề xuất"),
    ).toBeInTheDocument();
  });
});
