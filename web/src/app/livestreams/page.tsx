"use client";

import { useAuthGuard } from "@/lib/use-auth-guard";
import { LivestreamsPage } from "@/components/LivestreamsPage";

export default function Livestreams() {
  useAuthGuard();
  return <LivestreamsPage />;
}
