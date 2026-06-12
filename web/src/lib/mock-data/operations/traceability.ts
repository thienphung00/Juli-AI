import type { UnifiedOperationalDataModel, ValidatedWorkflowId } from "./schemas";
import { VALIDATED_WORKFLOW_IDS } from "./schemas";

const ALL_WORKFLOWS: ValidatedWorkflowId[] = [...VALIDATED_WORKFLOW_IDS];

const NEW_SHOP_WORKFLOWS: ValidatedWorkflowId[] = ["npl", "minimize_violations"];

const MID_LARGE_WORKFLOWS: ValidatedWorkflowId[] = [
  "budget_optimization",
  "product_scaling",
  "refund_spike_detection",
  "stockout_prevention",
];

/**
 * Datum→workflow traceability map (ADR-026 constraint #4).
 * Every collected field must map to ≥1 validated workflow_id.
 */
export const DATUM_TRACEABILITY_MAP: Record<string, ValidatedWorkflowId[]> = {
  "shop_metadata.shop_id": ALL_WORKFLOWS,
  "shop_metadata.shop_name": ALL_WORKFLOWS,
  "shop_metadata.profile": ALL_WORKFLOWS,
  "shop_metadata.probation_status": ALL_WORKFLOWS,
  "shop_metadata.graduation_date": ALL_WORKFLOWS,
  "shop_metadata.shop_age_days": ALL_WORKFLOWS,

  "probation.probation_start_date": NEW_SHOP_WORKFLOWS,
  "probation.probation_end_date": NEW_SHOP_WORKFLOWS,
  "probation.sps_current": NEW_SHOP_WORKFLOWS,
  "probation.sps_threshold": NEW_SHOP_WORKFLOWS,
  "probation.ahr_current": NEW_SHOP_WORKFLOWS,
  "probation.ahr_threshold": NEW_SHOP_WORKFLOWS,
  "probation.violations": ["minimize_violations"],
  "probation.violations[].violation_id": ["minimize_violations"],
  "probation.violations[].category": ["minimize_violations"],
  "probation.violations[].count": ["minimize_violations"],
  "probation.violations[].severity": ["minimize_violations"],

  "ad_campaigns": ["budget_optimization"],
  "ad_campaigns[].campaign_id": ["budget_optimization"],
  "ad_campaigns[].campaign_name": ["budget_optimization"],
  "ad_campaigns[].status": ["budget_optimization"],
  "ad_campaigns[].spend_vnd": ["budget_optimization"],
  "ad_campaigns[].impressions": ["budget_optimization"],
  "ad_campaigns[].clicks": ["budget_optimization"],
  "ad_campaigns[].ctr": ["budget_optimization"],
  "ad_campaigns[].conversions": ["budget_optimization"],
  "ad_campaigns[].revenue_vnd": ["budget_optimization"],
  "ad_campaigns[].roas": ["budget_optimization"],
  "ad_campaigns[].cpc_vnd": ["budget_optimization"],
  "ad_campaigns[].cpm_vnd": ["budget_optimization"],
  "ad_campaigns[].period_days": ["budget_optimization"],

  "products": ["npl", "product_scaling"],
  "products[].product_id": ["npl", "product_scaling"],
  "products[].sku_id": ["npl", "product_scaling"],
  "products[].product_name": ["npl", "product_scaling"],
  "products[].category": ["npl", "product_scaling"],
  "products[].units_sold_24h": ["product_scaling"],
  "products[].units_sold_7d": ["product_scaling"],
  "products[].units_sold_30d": ["product_scaling", "npl"],
  "products[].revenue_vnd_24h": ["product_scaling"],
  "products[].revenue_vnd_7d": ["product_scaling"],
  "products[].revenue_vnd_30d": ["product_scaling", "npl"],
  "products[].price_vnd": ["npl", "product_scaling"],
  "products[].margin_pct": ["product_scaling"],
  "products[].sell_through_rate": ["npl", "product_scaling"],

  "inventory": ["stockout_prevention", "product_scaling"],
  "inventory[].product_id": ["stockout_prevention", "product_scaling"],
  "inventory[].sku_id": ["stockout_prevention", "product_scaling"],
  "inventory[].inventory_level": ["stockout_prevention", "product_scaling"],
  "inventory[].sales_velocity_units_per_day": [
    "stockout_prevention",
    "product_scaling",
  ],
  "inventory[].reorder_lead_time_days": ["stockout_prevention"],

  "returns.refund_count_7d": ["refund_spike_detection"],
  "returns.refund_count_30d": ["refund_spike_detection"],
  "returns.refund_rate_7d": ["refund_spike_detection"],
  "returns.refund_rate_30d": ["refund_spike_detection"],
  "returns.baseline_refund_rate_30d": ["refund_spike_detection"],
  "returns.top_refund_reasons": ["refund_spike_detection"],
  "returns.top_refund_reasons[].reason": ["refund_spike_detection"],
  "returns.top_refund_reasons[].count_30d": ["refund_spike_detection"],
  "returns.top_refund_reasons[].share_pct": ["refund_spike_detection"],
  "returns.pending_return_authorizations": ["refund_spike_detection"],
  "returns.pending_return_authorizations[].return_id": ["refund_spike_detection"],
  "returns.pending_return_authorizations[].order_id": ["refund_spike_detection"],
  "returns.pending_return_authorizations[].product_name": ["refund_spike_detection"],
  "returns.pending_return_authorizations[].status": ["refund_spike_detection"],
  "returns.pending_return_authorizations[].refund_vnd": ["refund_spike_detection"],

  "health_data_source": ALL_WORKFLOWS,
  "collected_at": ALL_WORKFLOWS,
  "demo_persona_id": ALL_WORKFLOWS,
};

/** Envelope keys excluded from datum traceability (routing metadata only). */
export const TRACEABILITY_EXCLUDED_ROOT_KEYS = new Set<string>([]);

export function listTraceabilityDatumKeys(): string[] {
  return Object.keys(DATUM_TRACEABILITY_MAP).sort();
}

export function getWorkflowsForDatum(datumKey: string): ValidatedWorkflowId[] {
  return DATUM_TRACEABILITY_MAP[datumKey] ?? [];
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * Collects dot-path keys present in a fixture for traceability verification.
 * Array items use `[]` placeholder in paths (e.g. `products[].product_id`).
 */
export function collectModelDatumKeys(model: UnifiedOperationalDataModel): string[] {
  const keys = new Set<string>();

  function walk(value: unknown, path: string): void {
    if (value === null || value === undefined) {
      if (path) keys.add(path);
      return;
    }

    if (Array.isArray(value)) {
      keys.add(path);
      if (value.length === 0) return;
      const arrayPath = path ? `${path}[]` : "[]";
      for (const item of value) {
        walk(item, arrayPath);
      }
      return;
    }

    if (isObject(value)) {
      if (path) keys.add(path);
      for (const [key, nested] of Object.entries(value)) {
        if (nested === null || nested === undefined) continue;
        const nestedPath = path ? `${path}.${key}` : key;
        walk(nested, nestedPath);
      }
      return;
    }

    if (path) keys.add(path);
  }

  for (const [rootKey, rootValue] of Object.entries(model)) {
    if (TRACEABILITY_EXCLUDED_ROOT_KEYS.has(rootKey)) continue;
    if (rootValue === null || rootValue === undefined) continue;
    walk(rootValue, rootKey);
  }

  return normalizeDatumKeys([...keys]);
}

/** Drops container paths when more specific child paths exist in the set. */
function normalizeDatumKeys(keys: string[]): string[] {
  const sorted = [...keys].sort();
  return sorted.filter((key) => {
    const prefix = key.endsWith("[]") ? key : `${key}.`;
    const arrayPrefix = `${key}[].`;
    return !sorted.some(
      (other) =>
        other !== key &&
        (other.startsWith(prefix) || other.startsWith(arrayPrefix) || other.startsWith(`${key}[]`)),
    );
  });
}

export interface TraceabilityCheckResult {
  valid: boolean;
  unmappedKeys: string[];
  orphanMapKeys: string[];
  emptyWorkflowMappings: string[];
}

export function checkTraceability(model: UnifiedOperationalDataModel): TraceabilityCheckResult {
  const presentKeys = collectModelDatumKeys(model);
  const unmappedKeys = presentKeys.filter((key) => {
    const workflows = getWorkflowsForDatum(key);
    return workflows.length === 0;
  });

  const presentKeySet = new Set(presentKeys);
  const orphanMapKeys = listTraceabilityDatumKeys().filter((key) => {
    const root = key.split(".")[0]?.replace("[]", "") ?? key;
    if (root === "probation" && model.probation === null) return false;
    if (root === "probation" && model.shop_metadata.profile === "MID_LARGE_SHOP") {
      return false;
    }
    return !presentKeySet.has(key) && !key.includes("[]");
  });

  const emptyWorkflowMappings = listTraceabilityDatumKeys().filter(
    (key) => getWorkflowsForDatum(key).length === 0,
  );

  return {
    valid:
      unmappedKeys.length === 0 &&
      emptyWorkflowMappings.length === 0 &&
      orphanMapKeys.length === 0,
    unmappedKeys,
    orphanMapKeys,
    emptyWorkflowMappings,
  };
}

export function assertNoDatumsOutsideSignalRequirements(
  model: UnifiedOperationalDataModel,
): string[] {
  const allowed = new Set(listTraceabilityDatumKeys());
  return collectModelDatumKeys(model).filter((key) => !allowed.has(key));
}

/** JSON-serializable artifact for CI and docs consumers. */
export function exportTraceabilityArtifact(): {
  version: string;
  workflow_ids: ValidatedWorkflowId[];
  datum_map: Record<string, ValidatedWorkflowId[]>;
} {
  return {
    version: "1.0.0",
    workflow_ids: [...VALIDATED_WORKFLOW_IDS],
    datum_map: { ...DATUM_TRACEABILITY_MAP },
  };
}
