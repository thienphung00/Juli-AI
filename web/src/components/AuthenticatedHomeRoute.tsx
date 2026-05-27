"use client";

import { HomePage } from "@/components/HomePage";
import { useAuthGuard } from "@/lib/use-auth-guard";

function PageSpinner() {
  return (
    <div className="flex min-h-screen items-center justify-center">
      <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary-500 border-t-transparent" />
    </div>
  );
}

export function AuthenticatedHomeRoute() {
  const { loading } = useAuthGuard("require-auth");

  if (loading) {
    return <PageSpinner />;
  }

  return <HomePage />;
}
