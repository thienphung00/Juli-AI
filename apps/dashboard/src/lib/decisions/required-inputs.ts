import type { ValidatedWorkflowId } from "@/lib/mock-data/operations/schemas";

import type { RequiredInput } from "./types";

const WORKFLOW_REQUIRED_INPUTS: Record<ValidatedWorkflowId, RequiredInput[]> = {
  npl: [
    {
      key: "product_selection",
      label: "Chọn sản phẩm cần đăng",
      required: true,
    },
    {
      key: "listing_goal",
      label: "Mục tiêu listing (SPS / doanh thu)",
      required: true,
    },
  ],
  minimize_violations: [
    {
      key: "risk_tolerance",
      label: "Mức chấp nhận rủi ro vi phạm",
      required: true,
    },
  ],
  budget_optimization: [
    {
      key: "budget_limit",
      label: "Giới hạn ngân sách quảng cáo",
      required: true,
    },
    {
      key: "campaign_goal",
      label: "Mục tiêu chiến dịch (ROAS / GMV)",
      required: true,
    },
  ],
  product_scaling: [
    {
      key: "product_selection",
      label: "Chọn SKU cần mở rộng",
      required: true,
    },
    {
      key: "budget_limit",
      label: "Ngân sách quảng cáo cho SKU",
      required: false,
    },
  ],
  refund_spike_detection: [
    {
      key: "risk_tolerance",
      label: "Mức chấp nhận rủi ro hoàn tiền",
      required: true,
    },
  ],
  stockout_prevention: [
    {
      key: "sku_selection",
      label: "Chọn SKU cần đặt hàng bổ sung",
      required: true,
    },
    {
      key: "reorder_quantity",
      label: "Số lượng đặt hàng dự kiến",
      required: false,
    },
  ],
};

export function getRequiredInputsForWorkflow(
  workflowId: ValidatedWorkflowId,
): RequiredInput[] {
  return WORKFLOW_REQUIRED_INPUTS[workflowId].map((input) => ({ ...input }));
}
