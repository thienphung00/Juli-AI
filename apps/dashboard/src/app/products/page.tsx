"use client";

import { useAuthGuard } from "@/lib/use-auth-guard";
import { ProductsPage } from "@/components/ProductsPage";

export default function Products() {
  const { loading } = useAuthGuard("require-auth");
  if (loading) return null;
  return <ProductsPage />;
}
