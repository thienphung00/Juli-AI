import {
  VALIDATED_WORKFLOW_IDS,
  type ValidatedWorkflowId,
} from "@/lib/mock-data/operations/schemas";

export type TemplateControlType = "slider" | "toggle";

export interface TemplateSliderControl {
  id: string;
  type: "slider";
  label: string;
  description?: string;
  min: number;
  max: number;
  step: number;
  unit?: string;
  defaultValue: number;
}

export interface TemplateToggleControl {
  id: string;
  type: "toggle";
  label: string;
  description?: string;
  defaultEnabled: boolean;
}

export type TemplateControl = TemplateSliderControl | TemplateToggleControl;

export interface WorkflowTemplateDefinition {
  workflowId: ValidatedWorkflowId;
  displayName: string;
  controls: TemplateControl[];
}

const WORKFLOW_DISPLAY_NAMES: Record<ValidatedWorkflowId, string> = {
  npl: "Thêm sản phẩm mới",
  minimize_violations: "Giảm thiểu vi phạm",
  budget_optimization: "Tối ưu ngân sách quảng cáo",
  product_scaling: "Mở rộng sản phẩm",
  refund_spike_detection: "Phát hiện đỉnh hoàn tiền",
  stockout_prevention: "Phòng tránh hết hàng",
};

export const WORKFLOW_TEMPLATE_DEFINITIONS: WorkflowTemplateDefinition[] =
  VALIDATED_WORKFLOW_IDS.map((workflowId) => ({
    workflowId,
    displayName: WORKFLOW_DISPLAY_NAMES[workflowId],
    controls: buildControlsForWorkflow(workflowId),
  }));

function buildControlsForWorkflow(workflowId: ValidatedWorkflowId): TemplateControl[] {
  switch (workflowId) {
    case "npl":
      return [
        {
          id: "min_confidence",
          type: "slider",
          label: "Ngưỡng chất lượng tối thiểu",
          description: "Chỉ đề xuất listing khi điểm chất lượng đạt ngưỡng này.",
          min: 50,
          max: 95,
          step: 5,
          unit: "%",
          defaultValue: 70,
        },
        {
          id: "auto_suggest",
          type: "toggle",
          label: "Tự động đề xuất listing mới",
          description: "Đề xuất sản phẩm tiềm năng khi phát hiện cơ hội.",
          defaultEnabled: false,
        },
      ];
    case "minimize_violations":
      return [
        {
          id: "warning_threshold",
          type: "slider",
          label: "Ngưỡng cảnh báo vi phạm",
          min: 1,
          max: 10,
          step: 1,
          defaultValue: 3,
        },
        {
          id: "email_alerts",
          type: "toggle",
          label: "Thông báo email khi có vi phạm mới",
          defaultEnabled: true,
        },
      ];
    case "budget_optimization":
      return [
        {
          id: "target_roas",
          type: "slider",
          label: "ROAS mục tiêu",
          min: 1,
          max: 5,
          step: 0.1,
          defaultValue: 2.5,
        },
        {
          id: "auto_budget",
          type: "toggle",
          label: "Tự động điều chỉnh ngân sách",
          description: "Chỉ mô phỏng — không thực thi trên TikTok trong P1.8-9.",
          defaultEnabled: false,
        },
      ];
    case "product_scaling":
      return [
        {
          id: "revenue_threshold_m",
          type: "slider",
          label: "Ngưỡng doanh thu mở rộng",
          min: 5,
          max: 100,
          step: 5,
          unit: "tr ₫",
          defaultValue: 20,
        },
        {
          id: "competitor_analysis",
          type: "toggle",
          label: "Phân tích đối thủ trước khi mở rộng",
          defaultEnabled: true,
        },
      ];
    case "refund_spike_detection":
      return [
        {
          id: "refund_rate_threshold",
          type: "slider",
          label: "Ngưỡng % hoàn tiền",
          min: 1,
          max: 20,
          step: 1,
          unit: "%",
          defaultValue: 8,
        },
        {
          id: "pause_ads_on_spike",
          type: "toggle",
          label: "Tạm dừng quảng cáo khi phát hiện đỉnh",
          defaultEnabled: false,
        },
      ];
    case "stockout_prevention":
      return [
        {
          id: "min_days_cover",
          type: "slider",
          label: "Ngày tồn kho tối thiểu",
          min: 3,
          max: 30,
          step: 1,
          unit: "ngày",
          defaultValue: 7,
        },
        {
          id: "auto_reorder",
          type: "toggle",
          label: "Đặt hàng tự động (mô phỏng)",
          defaultEnabled: false,
        },
      ];
  }
}

export type WorkflowTemplateSession = Record<
  ValidatedWorkflowId,
  Record<string, number | boolean>
>;

export const WORKFLOW_TEMPLATES_SESSION_KEY = "juli-workflow-templates-session";

function buildDefaultSession(): WorkflowTemplateSession {
  const session = {} as WorkflowTemplateSession;

  for (const definition of WORKFLOW_TEMPLATE_DEFINITIONS) {
    const values: Record<string, number | boolean> = {};
    for (const control of definition.controls) {
      values[control.id] =
        control.type === "slider" ? control.defaultValue : control.defaultEnabled;
    }
    session[definition.workflowId] = values;
  }

  return session;
}

export function loadWorkflowTemplatesSession(): WorkflowTemplateSession {
  if (typeof window === "undefined") {
    return buildDefaultSession();
  }

  try {
    const raw = sessionStorage.getItem(WORKFLOW_TEMPLATES_SESSION_KEY);
    if (!raw) {
      return buildDefaultSession();
    }

    const parsed = JSON.parse(raw) as Partial<WorkflowTemplateSession>;
    const defaults = buildDefaultSession();

    for (const workflowId of VALIDATED_WORKFLOW_IDS) {
      defaults[workflowId] = {
        ...defaults[workflowId],
        ...(parsed[workflowId] ?? {}),
      };
    }

    return defaults;
  } catch {
    return buildDefaultSession();
  }
}

export function saveWorkflowTemplatesSession(session: WorkflowTemplateSession): void {
  if (typeof window === "undefined") {
    return;
  }

  sessionStorage.setItem(WORKFLOW_TEMPLATES_SESSION_KEY, JSON.stringify(session));
}

export function clearWorkflowTemplatesSession(): void {
  if (typeof window === "undefined") {
    return;
  }

  sessionStorage.removeItem(WORKFLOW_TEMPLATES_SESSION_KEY);
}

export function updateTemplateControlValue(
  session: WorkflowTemplateSession,
  workflowId: ValidatedWorkflowId,
  controlId: string,
  value: number | boolean,
): WorkflowTemplateSession {
  return {
    ...session,
    [workflowId]: {
      ...session[workflowId],
      [controlId]: value,
    },
  };
}
