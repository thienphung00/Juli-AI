import {
  collectForbiddenPiiKeys,
  isMaskedBuyerId,
} from "@/lib/mock-data/seller-personas/pii";
import type {
  MockAffiliateEvent,
  MockOrder,
  MockReturn,
  SellerPersona,
} from "@/lib/mock-data/seller-personas/schemas";

export interface ProfileMetricRef {
  key: string;
  value: string;
}

export interface ResolvedEvidence {
  orders: MockOrder[];
  returns: MockReturn[];
  affiliate_events: MockAffiliateEvent[];
  profile_metrics: ProfileMetricRef[];
}

function parseProfileRef(ref: string): ProfileMetricRef | null {
  const match = /^profile:(.+?)=(.+)$/.exec(ref);
  if (!match) return null;
  return { key: match[1], value: match[2] };
}

export function resolveEvidence(
  persona: SellerPersona,
  evidenceRefs: string[],
): ResolvedEvidence {
  const orders: MockOrder[] = [];
  const returns: MockReturn[] = [];
  const affiliate_events: MockAffiliateEvent[] = [];
  const profile_metrics: ProfileMetricRef[] = [];

  for (const ref of evidenceRefs) {
    const profileMetric = parseProfileRef(ref);
    if (profileMetric) {
      profile_metrics.push(profileMetric);
      continue;
    }

    const order = persona.orders.find((o) => o.id === ref);
    if (order) {
      orders.push(order);
      continue;
    }

    const ret = persona.returns.find((r) => r.id === ref);
    if (ret) {
      returns.push(ret);
      continue;
    }

    const affiliate = persona.affiliate_events.find((a) => a.id === ref);
    if (affiliate) {
      affiliate_events.push(affiliate);
    }
  }

  return { orders, returns, affiliate_events, profile_metrics };
}

export function assertEvidenceHasNoRawPii(evidence: ResolvedEvidence): void {
  const violations = collectForbiddenPiiKeys(evidence);
  if (violations.length > 0) {
    throw new Error(`Evidence contains forbidden PII keys: ${violations.join(", ")}`);
  }

  for (const order of evidence.orders) {
    if (!isMaskedBuyerId(order.buyer_id)) {
      throw new Error(`Unmasked buyer_id in order evidence: ${order.id}`);
    }
  }

  for (const ret of evidence.returns) {
    if (!isMaskedBuyerId(ret.buyer_id)) {
      throw new Error(`Unmasked buyer_id in return evidence: ${ret.id}`);
    }
  }

  for (const event of evidence.affiliate_events) {
    if (!/^aff_\*\*\*/.test(event.affiliate_id)) {
      throw new Error(`Unmasked affiliate_id in evidence: ${event.id}`);
    }
  }
}
