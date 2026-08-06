/**
 * Banned patterns in seller-facing copy across Demo UI.
 * Enforced repo-wide to maintain consistency.
 *
 * CRITICAL: This list forbids:
 * - Internal implementation details (tool_name, workflow_key, FBS/FBT internal IDs)
 * - False security claims (virus, antivirus, malware, "an toàn")
 *   The file validation catches bad MIME types and truncation only, not threats.
 *   Affirmative safety language ("tệp an toàn", "kiểm tra an toàn") is forbidden.
 */
export const SELLER_COPY_BANNED_PATTERNS = [
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
  /\bexecutor\b/i,
  /\bCreate Packages\b/i,
  /\bship\b/i,
  /\bsplit\b/i,
  /\bconfirm\b/i,
  /\bDeactivate\b/i,
  /\bparity\b/i,
  /\bActivity\b/,
  /Get Activity/i,
  // False security claims — file validation is MIME type and truncation only
  /\bvirus\b/i,
  /\bviruses\b/i,
  /antivirus/i,
  /malware/i,
  /\ban toàn\b/i,  // Vietnamese: "safe/safety" — forbid affirmative safety claims
  /kiểm tra an toàn/i,
  /tệp an toàn/i,
] as const;
