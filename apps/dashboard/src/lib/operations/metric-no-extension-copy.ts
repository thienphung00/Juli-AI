export function formatNoEstimatedExtensionCopy(
  metricKey: string,
  hasWorkflowLink: boolean,
): string {
  if (metricKey === "pending_return_count") {
    return "Chưa có yêu cầu hoàn tiền chờ — không ước tính lợi ích từ thanh này.";
  }

  if (hasWorkflowLink) {
    return "Không có đoạn dự kiến — xem gợi ý từ Juli phía trên.";
  }

  return "Chưa có dự kiến cải thiện cho chỉ số này.";
}
