"use client";

import { ModeSelectionPage } from "@/components/ModeSelectionPage";
import { useAuthGuard } from "@/lib/use-auth-guard";

function PageSpinner() {
  return (
    <div className="flex min-h-screen items-center justify-center">
      <div className="spinner" role="status" aria-label="Đang tải" />
    </div>
  );
}

export default function ModeSelectRoute() {
  const { loading: authLoading } = useAuthGuard("require-auth");

  if (authLoading) {
    return <PageSpinner />;
  }

  return <ModeSelectionPage />;
}
