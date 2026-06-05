import type {
  MockTask,
  PersonaId,
  SellerPersona,
  WorkflowId,
} from "@/lib/mock-data/seller-personas/schemas";
import { classifySellerStage } from "@/lib/seller-stage-router";

export interface WorkflowEntry {
  stage: PersonaId;
  workflowId: WorkflowId;
  label: string;
  description: string;
}

export const WORKFLOW_ENTRIES: Record<PersonaId, WorkflowEntry> = {
  new: {
    stage: "new",
    workflowId: "new_seller",
    label: "Copilot Người Bán Mới",
    description: "Hướng dẫn đạt đơn hàng có lãi đầu tiên",
  },
  leakage: {
    stage: "leakage",
    workflowId: "leakage",
    label: "Phát Hiện Rò Rỉ Doanh Thu",
    description: "Theo dõi hoàn trả, hoàn tiền và gian lận affiliate",
  },
  growth: {
    stage: "growth",
    workflowId: "growth",
    label: "Copilot Tăng Trưởng",
    description: "Tối ưu ROAS và mở rộng chiến dịch quảng cáo",
  },
};

export const PERSONA_SWITCHER_LABELS: Record<PersonaId, string> = {
  new: "Người bán mới",
  leakage: "Rò rỉ doanh thu",
  growth: "Tăng trưởng",
};

export function resolveSellerWorkflow(persona: SellerPersona): WorkflowEntry {
  const stage = classifySellerStage(persona.profile);
  return WORKFLOW_ENTRIES[stage];
}

export function getWorkflowTasks(
  persona: SellerPersona,
  workflowId: WorkflowId,
): MockTask[] {
  return persona.tasks.filter((task) => task.workflow === workflowId);
}
