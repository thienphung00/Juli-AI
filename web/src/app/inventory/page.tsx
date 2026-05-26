"use client";

import { useAuthGuard } from "@/lib/use-auth-guard";
import { InventoryPage } from "@/components/InventoryPage";

export default function Inventory() {
  const { loading } = useAuthGuard("require-auth");
  if (loading) return null;
  return <InventoryPage />;
}
