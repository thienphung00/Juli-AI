import type { ProductDraft } from "@/lib/mock-data/listing-workflow/schemas";

export type ListingPath = "path_a" | "path_b";

export type ListingWorkflowStep =
  | "path_selection"
  | "product_form"
  | "constraints"
  | "opportunity_browse"
  | "distributor_pick"
  | "draft_review"
  | "export_placeholder";

export interface ProductFormData {
  product_name: string;
  category: string;
  price: number;
  brand?: string;
  description?: string;
}

export interface OpportunityConstraints {
  category: string;
  maxCapitalVnd: number;
  dropshipOnly: boolean;
}

export interface ListingWorkflowState {
  step: ListingWorkflowStep;
  path: ListingPath | null;
  productForm: ProductFormData | null;
  constraints: OpportunityConstraints | null;
  selectedOpportunityId: string | null;
  selectedDistributorId: string | null;
  draft: ProductDraft | null;
}

const DEFAULT_PRODUCT_FORM: ProductFormData = {
  product_name: "Serum Vitamin C 20ml",
  category: "Mỹ phẩm",
  price: 189_000,
  brand: "Mai Linh Beauty",
  description: "Serum vitamin C giúp làm sáng da và giảm thâm nám.",
};

const DEFAULT_CONSTRAINTS: OpportunityConstraints = {
  category: "Mỹ phẩm",
  maxCapitalVnd: 20_000_000,
  dropshipOnly: true,
};

export const INITIAL_LISTING_WORKFLOW_STATE: ListingWorkflowState = {
  step: "path_selection",
  path: null,
  productForm: null,
  constraints: null,
  selectedOpportunityId: null,
  selectedDistributorId: null,
  draft: null,
};

const PATH_A_STEPS: ListingWorkflowStep[] = [
  "path_selection",
  "product_form",
  "distributor_pick",
  "draft_review",
  "export_placeholder",
];

const PATH_B_STEPS: ListingWorkflowStep[] = [
  "path_selection",
  "constraints",
  "opportunity_browse",
  "distributor_pick",
  "draft_review",
  "export_placeholder",
];

function stepsForPath(path: ListingPath | null): ListingWorkflowStep[] {
  if (path === "path_a") return PATH_A_STEPS;
  if (path === "path_b") return PATH_B_STEPS;
  return ["path_selection"];
}

export function selectPath(
  state: ListingWorkflowState,
  path: ListingPath,
): ListingWorkflowState {
  // Selecting a path should immediately make the step actionable so
  // "Tiếp theo" isn't disabled until the user edits a field.
  if (path === "path_a") {
    return {
      ...INITIAL_LISTING_WORKFLOW_STATE,
      path,
      step: "product_form",
      productForm: DEFAULT_PRODUCT_FORM,
    };
  }

  return {
    ...INITIAL_LISTING_WORKFLOW_STATE,
    path,
    step: "constraints",
    constraints: DEFAULT_CONSTRAINTS,
  };
}

export function advanceStep(state: ListingWorkflowState): ListingWorkflowState {
  if (!state.path) return state;
  const steps = stepsForPath(state.path);
  const index = steps.indexOf(state.step);
  if (index < 0 || index >= steps.length - 1) return state;
  return { ...state, step: steps[index + 1]! };
}

export function goBackStep(state: ListingWorkflowState): ListingWorkflowState {
  if (!state.path) return state;
  const steps = stepsForPath(state.path);
  const index = steps.indexOf(state.step);
  if (index <= 0) return state;
  return { ...state, step: steps[index - 1]! };
}

export function canGoBack(state: ListingWorkflowState): boolean {
  if (!state.path) return false;
  const steps = stepsForPath(state.path);
  return steps.indexOf(state.step) > 0;
}

export function updateProductForm(
  state: ListingWorkflowState,
  productForm: ProductFormData,
): ListingWorkflowState {
  return { ...state, productForm };
}

export function updateConstraints(
  state: ListingWorkflowState,
  constraints: OpportunityConstraints,
): ListingWorkflowState {
  return { ...state, constraints };
}

export function selectOpportunity(
  state: ListingWorkflowState,
  opportunityId: string,
): ListingWorkflowState {
  return { ...state, selectedOpportunityId: opportunityId };
}

export function selectDistributor(
  state: ListingWorkflowState,
  distributorId: string,
): ListingWorkflowState {
  return { ...state, selectedDistributorId: distributorId };
}

export function setDraft(
  state: ListingWorkflowState,
  draft: ProductDraft,
): ListingWorkflowState {
  return { ...state, draft };
}
