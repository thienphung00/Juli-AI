import { describe, expect, it } from "vitest";

import {
  Card,
  ConfirmDialog,
  Dialog,
  Form,
  InteractiveCard,
  OtpField,
  PasswordField,
  Popover,
  Table,
  TableEmpty,
  TextField,
  UnavailableKpiPopover,
} from "@juli/ui";

describe("Demo import boundary for @juli/ui #413 surface compositions", () => {
  it("imports card, dialog, popover, form, and table exports from the shared package", () => {
    expect(Card).toBeTypeOf("function");
    expect(InteractiveCard).toBeTypeOf("function");
    expect(Dialog).toBeTypeOf("function");
    expect(ConfirmDialog).toBeTypeOf("function");
    expect(Popover).toBeTypeOf("function");
    expect(UnavailableKpiPopover).toBeTypeOf("function");
    expect(Form).toBeTypeOf("function");
    expect(TextField).toBeTypeOf("function");
    expect(PasswordField).toBeTypeOf("function");
    expect(OtpField).toBeTypeOf("function");
    expect(Table).toBeTypeOf("function");
    expect(TableEmpty).toBeTypeOf("function");
  });
});
