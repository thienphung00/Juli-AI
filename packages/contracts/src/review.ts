export type ReviewStage =
  | "why"
  | "analytics"
  | "inputs"
  | "preview"
  | "approve";

export interface ReviewInputFieldOption {
  label: string;
  value: string;
}

export type ReviewInputFieldKind = "option-list" | "upload" | "free-text";

export interface ReviewInputFieldDescriptor {
  key: string;
  label: string;
  prefillValue: string;
  required: boolean;
  editable: boolean;
  kind?: ReviewInputFieldKind;
  options?: ReviewInputFieldOption[];
}

export interface ReviewStageContent {
  stage: ReviewStage;
  title: string;
  body: string;
  analyticsMetricKey?: string;
  analyticsMetricHref?: string;
  inputFields?: ReviewInputFieldDescriptor[];
}
