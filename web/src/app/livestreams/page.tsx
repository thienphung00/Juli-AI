"use client";

import { useAuthGuard } from "@/lib/use-auth-guard";
import { LivestreamsPage } from "@/components/LivestreamsPage";

export default function Livestreams() {
  const { loading } = useAuthGuard("require-auth");
  if (loading) return null;
  return <LivestreamsPage />;
}
