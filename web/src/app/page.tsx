"use client";

import { HomePage } from "@/components/HomePage";
import { AuthenticatedHomeRoute } from "@/components/AuthenticatedHomeRoute";

const uiOnly = process.env.NEXT_PUBLIC_UI_ONLY === "1";

export default function Home() {
  if (uiOnly) {
    return <HomePage uiOnly />;
  }

  return <AuthenticatedHomeRoute />;
}
