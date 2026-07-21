export type SettingsCapabilityStatus = "supported" | "partial" | "unavailable";

export interface SettingsFieldDefinition {
  affectedWorkflowKeys?: readonly string[];
  defaultValue: string;
  editable: boolean;
  helperText?: string;
  key: string;
  label: string;
  max?: number;
  min?: number;
  unit?: string;
  unresolved?: boolean;
  unresolvedReason?: string;
}

export interface WorkflowTemplateDefinition {
  capabilityBadge: string;
  capabilityStatus: SettingsCapabilityStatus;
  displayName: string;
  enabled: boolean;
  fbtFields: SettingsFieldDefinition[];
  fields: SettingsFieldDefinition[];
  lastUpdatedAt: string;
  productDomain: string;
  productDomainLabel: string;
  toolName: string;
  workflowKey: string;
}

export interface ThresholdDefinition {
  affectedWorkflowKeys: readonly string[];
  defaultValue: string;
  editable: boolean;
  key: string;
  label: string;
  max?: number;
  min?: number;
  unit: string;
  unresolved?: boolean;
  unresolvedReason?: string;
}

export interface ProductDomainDefinition {
  id: string;
  label: string;
}

export const PRODUCT_DOMAIN_ORDER = [
  { id: "listing", label: "Danh sách sản phẩm" },
  { id: "inventory", label: "Tồn kho" },
  { id: "fulfillment", label: "Giao hàng" },
  { id: "promotion", label: "Khuyến mãi" },
  { id: "returns", label: "Hậu mãi" },
] as const satisfies readonly ProductDomainDefinition[];

const FBS_BADGE = "Có thể thực thi qua FBS";
const PARTIAL_BADGE = "Một phần — FBS";

function settingsFieldKey(workflowKey: string, fieldKey: string) {
  return `${workflowKey}:${fieldKey}`;
}

export function buildSettingsFieldStorageKey(
  workflowKey: string,
  fieldKey: string,
) {
  return settingsFieldKey(workflowKey, fieldKey);
}

export function buildThresholdStorageKey(thresholdKey: string) {
  return `threshold:${thresholdKey}`;
}

export const workflowTemplateFixtures = [
  {
    workflowKey: "create_hero_product_1",
    displayName: "Tạo sản phẩm nổi bật",
    toolName: "listing.create_hero_product",
    productDomain: "listing",
    productDomainLabel: "Danh sách sản phẩm",
    capabilityStatus: "partial",
    capabilityBadge: PARTIAL_BADGE,
    enabled: true,
    lastUpdatedAt: "2026-07-10T09:00:00+07:00",
    fields: [
      {
        key: "category_gap_min_days",
        label: "Số ngày theo dõi khoảng trống danh mục",
        defaultValue: "14",
        unit: "ngày",
        min: 7,
        max: 90,
        editable: true,
        helperText: "Ảnh hưởng đề xuất tạo sản phẩm nổi bật.",
        affectedWorkflowKeys: ["create_hero_product_1"],
      },
    ],
    fbtFields: [
      {
        key: "fbt_new_listing",
        label: "FBT — tạo sản phẩm mới",
        defaultValue: "",
        editable: false,
        unresolved: true,
        unresolvedReason:
          "Chưa xác định — không có executor FBT cho sản phẩm mới.",
      },
    ],
  },
  {
    workflowKey: "optimize_product_2",
    displayName: "Tối ưu sản phẩm",
    toolName: "listing.optimize_product",
    productDomain: "listing",
    productDomainLabel: "Danh sách sản phẩm",
    capabilityStatus: "supported",
    capabilityBadge: FBS_BADGE,
    enabled: true,
    lastUpdatedAt: "2026-07-11T10:30:00+07:00",
    fields: [
      {
        key: "min_conversion_rate",
        label: "Tỷ lệ chuyển đổi tối thiểu để đề xuất tối ưu",
        defaultValue: "0.02",
        unit: "%",
        min: 0.01,
        max: 0.5,
        editable: true,
        helperText: "Ảnh hưởng đề xuất tối ưu sản phẩm.",
        affectedWorkflowKeys: ["optimize_product_2"],
      },
    ],
    fbtFields: [],
  },
  {
    workflowKey: "replenish_inventory_3", // gitleaks:allow
    displayName: "Nhập thêm hàng",
    toolName: "inventory.replenish",
    productDomain: "inventory",
    productDomainLabel: "Tồn kho",
    capabilityStatus: "partial",
    capabilityBadge: PARTIAL_BADGE,
    enabled: true,
    lastUpdatedAt: "2026-07-12T08:15:00+07:00",
    fields: [
      {
        key: "reorder_days_threshold",
        label: "Ngưỡng cảnh báo hết hàng",
        defaultValue: "4",
        unit: "ngày",
        min: 3,
        max: 30,
        editable: true,
        helperText: "Ảnh hưởng đề xuất nhập thêm hàng.",
        affectedWorkflowKeys: ["replenish_inventory_3"], // gitleaks:allow
      },
    ],
    fbtFields: [
      {
        key: "fbt_replenish_intake",
        label: "FBT — nhập hàng",
        defaultValue: "",
        editable: false,
        unresolved: true,
        unresolvedReason:
          "Chưa xác định — không có executor FBT cho việc nhập hàng.",
      },
    ],
  },
  {
    workflowKey: "clear_excess_4",
    displayName: "Xả hàng tồn",
    toolName: "inventory.clear_excess",
    productDomain: "inventory",
    productDomainLabel: "Tồn kho",
    capabilityStatus: "supported",
    capabilityBadge: FBS_BADGE,
    enabled: true,
    lastUpdatedAt: "2026-07-12T11:00:00+07:00",
    fields: [
      {
        key: "excess_days_threshold",
        label: "Tuổi hàng tồn vượt ngưỡng",
        defaultValue: "60",
        unit: "ngày",
        min: 30,
        max: 180,
        editable: true,
        helperText: "Ảnh hưởng đề xuất xả hàng tồn.",
        affectedWorkflowKeys: ["clear_excess_4"],
      },
    ],
    fbtFields: [
      {
        key: "fbt_stock_update",
        label: "FBT — cập nhật tồn kho",
        defaultValue: "",
        editable: false,
        unresolved: true,
        unresolvedReason:
          "Chưa xác định — chỉ ghi nhận webhook cập nhật tồn kho FBT.",
      },
    ],
  },
  {
    workflowKey: "process_order_5",
    displayName: "Xử lý đơn hàng có rủi ro trễ hạn",
    toolName: "fulfillment.process_order",
    productDomain: "fulfillment",
    productDomainLabel: "Giao hàng",
    capabilityStatus: "partial",
    capabilityBadge: PARTIAL_BADGE,
    enabled: true,
    lastUpdatedAt: "2026-07-13T07:45:00+07:00",
    fields: [
      {
        key: "sla_warning_hours",
        label: "Cảnh báo trước hạn SLA",
        defaultValue: "6",
        unit: "giờ",
        min: 1,
        max: 24,
        editable: true,
        helperText: "Ảnh hưởng đề xuất xử lý đơn hàng.",
        affectedWorkflowKeys: ["process_order_5"],
      },
    ],
    fbtFields: [
      {
        key: "process_order_5b",
        label: "FBT intake process_order_5b",
        defaultValue: "",
        editable: false,
        unresolved: true,
        unresolvedReason:
          "Chưa xác định — không hiển thị Create Packages, nhãn vận chuyển, ship, split, hoặc confirm cho FBT.",
      },
    ],
  },
  {
    workflowKey: "create_activity_7a",
    displayName: "Tạo chương trình khuyến mãi",
    toolName: "promotion.create_activity",
    productDomain: "promotion",
    productDomainLabel: "Khuyến mãi",
    capabilityStatus: "partial",
    capabilityBadge: PARTIAL_BADGE,
    enabled: true,
    lastUpdatedAt: "2026-07-14T09:20:00+07:00",
    fields: [
      {
        key: "promotion_lead_days",
        label: "Số ngày chuẩn bị trước khuyến mãi",
        defaultValue: "3",
        unit: "ngày",
        min: 1,
        max: 14,
        editable: true,
        helperText: "Ảnh hưởng đề xuất tạo chương trình khuyến mãi.",
        affectedWorkflowKeys: ["create_activity_7a"],
      },
    ],
    fbtFields: [
      {
        key: "fbt_promotion_parity",
        label: "FBT — khuyến mãi",
        defaultValue: "",
        editable: false,
        unresolved: true,
        unresolvedReason:
          "Chưa xác định — không suy diễn parity khuyến mãi từ FBS sang FBT.",
      },
    ],
  },
  {
    workflowKey: "update_activity_7c",
    displayName: "Cập nhật chương trình khuyến mãi",
    toolName: "promotion.update_activity",
    productDomain: "promotion",
    productDomainLabel: "Khuyến mãi",
    capabilityStatus: "supported",
    capabilityBadge: FBS_BADGE,
    enabled: true,
    lastUpdatedAt: "2026-07-14T10:00:00+07:00",
    fields: [
      {
        key: "update_review_days",
        label: "Chu kỳ xem xét hiệu suất khuyến mãi",
        defaultValue: "7",
        unit: "ngày",
        min: 3,
        max: 30,
        editable: true,
        helperText: "Ảnh hưởng đề xuất cập nhật chương trình khuyến mãi.",
        affectedWorkflowKeys: ["update_activity_7c"],
      },
    ],
    fbtFields: [
      {
        key: "fbt_promotion_update",
        label: "FBT — cập nhật khuyến mãi",
        defaultValue: "",
        editable: false,
        unresolved: true,
        unresolvedReason: "Chưa xác định — luồng FBT cho khuyến mãi chưa có executor.",
      },
    ],
  },
  {
    workflowKey: "delete_activity_7b",
    displayName: "Kết thúc chương trình khuyến mãi",
    toolName: "promotion.delete_activity",
    productDomain: "promotion",
    productDomainLabel: "Khuyến mãi",
    capabilityStatus: "supported",
    capabilityBadge: FBS_BADGE,
    enabled: true,
    lastUpdatedAt: "2026-07-14T10:45:00+07:00",
    fields: [
      {
        key: "end_grace_days",
        label: "Số ngày ân hạn sau khi hết hạn",
        defaultValue: "1",
        unit: "ngày",
        min: 0,
        max: 7,
        editable: true,
        helperText: "Ảnh hưởng đề xuất kết thúc chương trình khuyến mãi.",
        affectedWorkflowKeys: ["delete_activity_7b"],
      },
    ],
    fbtFields: [],
  },
  {
    workflowKey: "prevent_cancellation_8a",
    displayName: "Xử lý yêu cầu huỷ đơn",
    toolName: "returns.prevent_cancellation",
    productDomain: "returns",
    productDomainLabel: "Hậu mãi",
    capabilityStatus: "supported",
    capabilityBadge: FBS_BADGE,
    enabled: true,
    lastUpdatedAt: "2026-07-15T08:00:00+07:00",
    fields: [
      {
        key: "cancellation_review_hours",
        label: "Thời gian xem xét yêu cầu huỷ",
        defaultValue: "12",
        unit: "giờ",
        min: 1,
        max: 48,
        editable: true,
        helperText: "Ảnh hưởng đề xuất xử lý yêu cầu huỷ đơn.",
        affectedWorkflowKeys: ["prevent_cancellation_8a"],
      },
    ],
    fbtFields: [],
  },
  {
    workflowKey: "prevent_return_8b",
    displayName: "Xử lý yêu cầu trả hàng",
    toolName: "returns.prevent_return",
    productDomain: "returns",
    productDomainLabel: "Hậu mãi",
    capabilityStatus: "partial",
    capabilityBadge: PARTIAL_BADGE,
    enabled: true,
    lastUpdatedAt: "2026-07-15T08:30:00+07:00",
    fields: [
      {
        key: "return_review_hours",
        label: "Thời gian xem xét yêu cầu trả hàng",
        defaultValue: "24",
        unit: "giờ",
        min: 4,
        max: 72,
        editable: true,
        helperText: "Ảnh hưởng đề xuất xử lý yêu cầu trả hàng.",
        affectedWorkflowKeys: ["prevent_return_8b"],
      },
    ],
    fbtFields: [
      {
        key: "fbt_return_handling",
        label: "FBT — xử lý trả hàng",
        defaultValue: "",
        editable: false,
        unresolved: true,
        unresolvedReason:
          "Chưa xác định — luồng FBT chỉ ghi nhận, chưa hỗ trợ xử lý trực tiếp.",
      },
    ],
  },
  {
    workflowKey: "prevent_refund_8c",
    displayName: "Xử lý yêu cầu hoàn tiền",
    toolName: "returns.prevent_refund",
    productDomain: "returns",
    productDomainLabel: "Hậu mãi",
    capabilityStatus: "supported",
    capabilityBadge: FBS_BADGE,
    enabled: true,
    lastUpdatedAt: "2026-07-15T09:00:00+07:00",
    fields: [
      {
        key: "refund_review_hours",
        label: "Thời gian xem xét yêu cầu hoàn tiền",
        defaultValue: "8",
        unit: "giờ",
        min: 2,
        max: 48,
        editable: true,
        helperText: "Ảnh hưởng đề xuất xử lý yêu cầu hoàn tiền.",
        affectedWorkflowKeys: ["prevent_refund_8c"],
      },
    ],
    fbtFields: [],
  },
] as const satisfies readonly WorkflowTemplateDefinition[];

export const thresholdFixtures = [
  {
    key: "global_stockout_days",
    label: "Ngưỡng cảnh báo hết hàng toàn shop",
    defaultValue: "4",
    unit: "ngày",
    min: 2,
    max: 30,
    editable: true,
    affectedWorkflowKeys: ["replenish_inventory_3"], // gitleaks:allow
  },
  {
    key: "global_excess_days",
    label: "Tuổi hàng tồn vượt ngưỡng toàn shop",
    defaultValue: "60",
    unit: "ngày",
    min: 30,
    max: 180,
    editable: true,
    affectedWorkflowKeys: ["clear_excess_4"],
  },
  {
    key: "global_sla_hours",
    label: "Cảnh báo SLA giao hàng",
    defaultValue: "6",
    unit: "giờ",
    min: 1,
    max: 24,
    editable: true,
    affectedWorkflowKeys: ["process_order_5"],
  },
  {
    key: "fbt_trigger_contract",
    label: "Hợp đồng trigger FBT",
    defaultValue: "",
    unit: "",
    editable: false,
    unresolved: true,
    unresolvedReason:
      "Chưa xác định — thay đổi ngưỡng không tạo trigger FBT mới.",
    affectedWorkflowKeys: [
      "create_hero_product_1",
      "replenish_inventory_3", // gitleaks:allow
      "process_order_5",
    ],
  },
] as const satisfies readonly ThresholdDefinition[];

export function getWorkflowTemplate(workflowKey: string) {
  return workflowTemplateFixtures.find(
    (template) => template.workflowKey === workflowKey,
  );
}

export function groupWorkflowTemplatesByDomain() {
  return PRODUCT_DOMAIN_ORDER.map((domain) => ({
    ...domain,
    templates: workflowTemplateFixtures.filter(
      (template) => template.productDomain === domain.id,
    ),
  }));
}

export function getDefaultSettingsValues(): Record<string, string> {
  const defaults: Record<string, string> = {};

  for (const template of workflowTemplateFixtures) {
    for (const field of template.fields) {
      defaults[buildSettingsFieldStorageKey(template.workflowKey, field.key)] =
        field.defaultValue;
    }
  }

  for (const threshold of thresholdFixtures) {
    defaults[buildThresholdStorageKey(threshold.key)] = threshold.defaultValue;
  }

  return defaults;
}
