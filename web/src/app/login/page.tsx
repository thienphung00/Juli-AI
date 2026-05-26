"use client";

import { useAuthGuard } from "@/lib/use-auth-guard";
import { LoginForm } from "@/components/LoginForm";

export default function LoginPage() {
  const { loading } = useAuthGuard("require-guest");

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary-500 border-t-transparent" />
      </div>
    );
  }

  return <LoginForm />;
}
