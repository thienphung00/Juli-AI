"use client";

import { useAuthGuard } from "@/lib/use-auth-guard";
import { ProductsPage } from "@/components/ProductsPage";

export default function Products() {
  useAuthGuard();
  return <ProductsPage />;
}
