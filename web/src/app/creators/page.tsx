"use client";

import { useAuthGuard } from "@/lib/use-auth-guard";
import { CreatorsPage } from "@/components/CreatorsPage";

export default function Creators() {
  useAuthGuard();
  return <CreatorsPage />;
}
