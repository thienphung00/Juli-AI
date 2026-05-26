"use client";

import { useAuthGuard } from "@/lib/use-auth-guard";
import { InventoryPage } from "@/components/InventoryPage";

export default function Inventory() {
  useAuthGuard();
  return <InventoryPage />;
}
