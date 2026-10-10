"use client";

import { useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { AcceptInvite } from "../../components/accept-invite";

function Inner() {
  const params = useSearchParams();
  return <AcceptInvite inviteToken={params.get("token")} />;
}

export default function AcceptInvitePage() {
  return (
    <Suspense fallback={null}>
      <Inner />
    </Suspense>
  );
}
