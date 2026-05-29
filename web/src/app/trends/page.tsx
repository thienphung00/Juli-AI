"use client";

import { TrendsPage } from "@/components/TrendsPage";
import { useAuthGuard } from "@/lib/use-auth-guard";
import { useModeGuard } from "@/lib/use-mode-guard";

export default function TrendsRoute() {
  const { loading: authLoading } = useAuthGuard("require-auth");
  const { loading: modeLoading } = useModeGuard("require-mode");

  if (authLoading || modeLoading) return null;
  return <TrendsPage />;
}
