export type ReviewStage =
  | "why"
  | "analytics"
  | "inputs"
  | "preview"
  | "approve";

export interface ReviewInputFieldDescriptor {
  key: string;
  label: string;
  prefillValue: string;
  required: boolean;
  editable: boolean;
}

export interface ReviewStageContent {
  stage: ReviewStage;
  title: string;
  body: string;
  analyticsMetricKey?: string;
  analyticsMetricHref?: string;
  inputFields?: ReviewInputFieldDescriptor[];
}
