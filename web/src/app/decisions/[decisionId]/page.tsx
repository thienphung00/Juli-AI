"use client";

import { useAuthGuard } from "@/lib/use-auth-guard";
import { useModeGuard } from "@/lib/use-mode-guard";

import { DecisionDetailPage } from "@/components/decisions/DecisionDetailPage";

export default function DecisionDetailRoute({
  params,
}: {
  params: { decisionId: string };
}) {
  const { loading: authLoading } = useAuthGuard("require-auth");
  const { loading: modeLoading } = useModeGuard("require-mode");

  if (authLoading || modeLoading) return null;
  return <DecisionDetailPage decisionId={params.decisionId} />;
}
