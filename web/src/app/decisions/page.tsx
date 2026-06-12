"use client";

import { DecisionsPage } from "@/components/DecisionsPage";
import { useAuthGuard } from "@/lib/use-auth-guard";
import { useModeGuard } from "@/lib/use-mode-guard";

export default function DecisionsRoute() {
  const { loading: authLoading } = useAuthGuard("require-auth");
  const { loading: modeLoading } = useModeGuard("require-mode");

  if (authLoading || modeLoading) return null;
  return <DecisionsPage />;
}
