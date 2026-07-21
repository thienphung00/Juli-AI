import type { SettingsFieldDefinition, ThresholdDefinition } from "./fixtures";

type ValidatableField = Pick<
  SettingsFieldDefinition | ThresholdDefinition,
  "defaultValue" | "key" | "label" | "max" | "min" | "unit"
>;

export function getEffectiveSettingsValue(
  field: ValidatableField,
  draft: Record<string, string>,
  saved: Record<string, string>,
  storageKey?: string,
) {
  const key = storageKey ?? field.key;

  if (key in draft) {
    return draft[key];
  }

  if (key in saved) {
    return saved[key];
  }

  return field.defaultValue;
}

export function validateSettingsField(
  field: ValidatableField,
  value: string,
): string | null {
  if (value.trim() === "") {
    return `${field.label}: vui lòng nhập giá trị.`;
  }

  if (field.min === undefined || field.max === undefined) {
    return null;
  }

  const numericValue = Number(value);

  if (!Number.isFinite(numericValue)) {
    return `${field.label}: vui lòng nhập số hợp lệ.`;
  }

  if (numericValue < field.min || numericValue > field.max) {
    const unitSuffix = field.unit ? ` ${field.unit}` : "";
    return `${field.label}: giá trị hợp lệ ${field.min}–${field.max}${unitSuffix}.`;
  }

  return null;
}

export function formatAllowedRange(field: ValidatableField) {
  if (field.min === undefined || field.max === undefined) {
    return "";
  }

  const unitSuffix = field.unit ? ` ${field.unit}` : "";
  return `Giá trị hợp lệ: ${field.min}–${field.max}${unitSuffix}.`;
}
