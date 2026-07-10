import type { LeakageEvidenceBundle } from "@/lib/mock-data/leakage-workflow/schemas";
import {
  collectForbiddenPiiKeys,
  isMaskedBuyerId,
} from "@/lib/mock-data/seller-personas/pii";

export function assertLeakageEvidenceHasNoRawPii(
  bundle: LeakageEvidenceBundle,
): void {
  const violations = collectForbiddenPiiKeys(bundle);
  if (violations.length > 0) {
    throw new Error(
      `Evidence contains forbidden PII keys: ${violations.join(", ")}`,
    );
  }

  for (const order of bundle.orders) {
    if (!isMaskedBuyerId(order.buyer_id)) {
      throw new Error(`Unmasked buyer_id in order evidence: ${order.id}`);
    }
  }

  for (const ret of bundle.returns) {
    if (!isMaskedBuyerId(ret.buyer_id)) {
      throw new Error(`Unmasked buyer_id in return evidence: ${ret.id}`);
    }
  }
}

export function checkLeakageEvidencePii(bundle: LeakageEvidenceBundle): boolean {
  try {
    assertLeakageEvidenceHasNoRawPii(bundle);
    return true;
  } catch {
    return false;
  }
}
