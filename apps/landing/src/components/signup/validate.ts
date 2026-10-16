import { FIELDS, ROLE_OPTIONS } from "./signup-content";

/**
 * The browser-side twin of `backend/src/juli_backend/services/trial_signups.py`
 * `validate()`: same rules, same Vietnamese messages. The server stays the
 * authority — this only saves a round trip and shows errors inline.
 */

export const MESSAGES = {
  full_name: "Vui lòng nhập họ tên (2–120 ký tự).",
  phone: "Số điện thoại chưa đúng, hãy nhập số di động Việt Nam, ví dụ 0912 345 678.",
  email: "Email chưa đúng, ví dụ ten@congty.vn.",
  shop: "Vui lòng nhập tên hoặc link shop TikTok (2–300 ký tự).",
  role: "Vui lòng chọn vai trò.",
  note: "Ghi chú tối đa 1.000 ký tự.",
  consent: "Vui lòng đồng ý với Điều khoản dịch vụ và Chính sách bảo mật.",
} as const;

export type SignupErrors = Partial<Record<keyof typeof MESSAGES, string>>;

export interface SignupValues {
  full_name: string;
  phone: string;
  email: string;
  shop: string;
  role: string;
  note: string;
  consent: boolean;
  website: string;
}

/** Same pattern the inputs carry for no-JS browsers (`pattern` attribute). */
export const PHONE_PATTERN = String.raw`[\s\(]*(\+?84|0)[\s.\-\(\)]*[35789]([\s.\-\(\)]*\d){8}\s*`;

const PHONE_RE = /^0[35789]\d{8}$/;
const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$/;
const ROLES = new Set(ROLE_OPTIONS.map((option) => option.value));

const squash = (value: string) => value.split(/\s+/).filter(Boolean).join(" ");

/** `+84 912-345-678` / `84912345678` / `0912.345.678` → `0912345678`; else null. */
export function normalizePhone(raw: string): string | null {
  let digits = (raw ?? "").replace(/[\s.\-()]/g, "");
  if (digits.startsWith("+84")) digits = `0${digits.slice(3)}`;
  else if (digits.startsWith("84") && digits.length === 11) digits = `0${digits.slice(2)}`;
  return PHONE_RE.test(digits) ? digits : null;
}

export function validateSignup(values: SignupValues): SignupErrors {
  const errors: SignupErrors = {};
  const name = squash(values.full_name);
  if (name.length < 2 || name.length > 120) errors.full_name = MESSAGES.full_name;
  if (normalizePhone(values.phone) === null) errors.phone = MESSAGES.phone;
  const email = squash(values.email).toLowerCase();
  if (email.length > 254 || !EMAIL_RE.test(email)) errors.email = MESSAGES.email;
  const shop = squash(values.shop);
  if (shop.length < 2 || shop.length > 300) errors.shop = MESSAGES.shop;
  if (!ROLES.has(values.role)) errors.role = MESSAGES.role;
  if (values.note.trim().length > 1000) errors.note = MESSAGES.note;
  if (!values.consent) errors.consent = MESSAGES.consent;
  return errors;
}

/** Field order on the page — the first invalid one gets focus. */
export const FIELD_ORDER: readonly (keyof typeof MESSAGES)[] = [
  FIELDS.fullName,
  FIELDS.phone,
  FIELDS.email,
  FIELDS.shop,
  FIELDS.role,
  FIELDS.note,
  FIELDS.consent,
];
