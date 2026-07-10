"use client";

import { AiChatPage } from "@/components/AiChatPage";
import { useAuthGuard } from "@/lib/use-auth-guard";
import { useModeGuard } from "@/lib/use-mode-guard";

export default function AiChatRoute() {
  const { loading: authLoading } = useAuthGuard("require-auth");
  const { loading: modeLoading } = useModeGuard("require-mode");

  if (authLoading || modeLoading) return null;
  return <AiChatPage />;
}
