/** Keys that must never appear in Phase 1 mock fixtures (data-sources.md #17). */
export const FORBIDDEN_PII_KEYS = [
  "buyer_name",
  "buyer_email",
  "buyer_phone",
  "buyer_address",
  "email",
  "phone",
  "phone_number",
  "address",
  "full_name",
  "real_name",
  "dm_content",
  "private_chat",
] as const;

const MASKED_BUYER_ID_PATTERN = /^buyer_[*x\d]+$/i;

export function isMaskedBuyerId(value: string): boolean {
  return MASKED_BUYER_ID_PATTERN.test(value);
}

export function collectForbiddenPiiKeys(value: unknown, path = ""): string[] {
  if (value === null || typeof value !== "object") {
    return [];
  }

  const violations: string[] = [];

  if (Array.isArray(value)) {
    value.forEach((item, index) => {
      violations.push(...collectForbiddenPiiKeys(item, `${path}[${index}]`));
    });
    return violations;
  }

  for (const [key, nested] of Object.entries(value)) {
    const keyPath = path ? `${path}.${key}` : key;
    if (FORBIDDEN_PII_KEYS.includes(key as (typeof FORBIDDEN_PII_KEYS)[number])) {
      violations.push(keyPath);
    }
    violations.push(...collectForbiddenPiiKeys(nested, keyPath));
  }

  return violations;
}
