export interface HeaderAlert {
  id: string;
  title: string;
  message: string;
  severity: "info" | "warning" | "critical";
}

export const MOCK_HEADER_ALERTS: HeaderAlert[] = [
  {
    id: "alert-1",
    title: "Tồn kho thấp",
    message: "SKU Áo thun basic còn 12 đơn vị — nên nhập thêm trong 48h.",
    severity: "warning",
  },
  {
    id: "alert-2",
    title: "Livestream đang diễn ra",
    message: "Phiên live #2841 đạt 1.2K người xem — GMV tăng 18% so với trung bình.",
    severity: "info",
  },
];
