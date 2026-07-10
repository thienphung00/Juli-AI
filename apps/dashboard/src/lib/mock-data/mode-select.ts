import type { WorkspaceMode } from "@/lib/workspace-mode";

export interface ModeSelectOption {
  mode: WorkspaceMode;
  title: string;
  description: string;
}

export const MODE_SELECT_OPTIONS: ModeSelectOption[] = [
  {
    mode: "seller",
    title: "Người bán",
    description: "Quản lý cửa hàng, GMV, livestream và vận hành shop của bạn.",
  },
  {
    mode: "affiliate",
    title: "Affiliate",
    description: "Theo dõi hoa hồng, sản phẩm trending và đơn hàng affiliate.",
  },
];
