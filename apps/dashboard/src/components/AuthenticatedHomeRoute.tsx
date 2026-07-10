"use client";

import { HomePage } from "@/components/HomePage";
import { useAuthGuard } from "@/lib/use-auth-guard";
import { useModeGuard } from "@/lib/use-mode-guard";
import { isUiOnly } from "@/lib/ui-only";

function PageSpinner() {
  return (
    <div className="flex min-h-screen items-center justify-center">
      <div className="spinner" role="status" aria-label="Đang tải" />
    </div>
  );
}

export function AuthenticatedHomeRoute() {
  const { loading: authLoading } = useAuthGuard("require-auth");
  const { loading: modeLoading } = useModeGuard("require-mode");

  if (authLoading || modeLoading) {
    return <PageSpinner />;
  }

  return <HomePage uiOnly={isUiOnly} />;
}
