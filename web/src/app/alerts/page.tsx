"use client";

import { useAuthGuard } from "@/lib/use-auth-guard";
import { AlertsPage } from "@/components/AlertsPage";

export default function Alerts() {
  const { loading } = useAuthGuard("require-auth");

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary-500 border-t-transparent" />
      </div>
    );
  }

  return <AlertsPage />;
}

