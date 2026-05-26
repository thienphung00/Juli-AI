"use client";

import { useAuthGuard } from "@/lib/use-auth-guard";
import { CreatorsPage } from "@/components/CreatorsPage";

export default function Creators() {
  const { loading } = useAuthGuard("require-auth");
  if (loading) return null;
  return <CreatorsPage />;
}
