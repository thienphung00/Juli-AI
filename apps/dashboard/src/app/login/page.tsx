import { notFound } from "next/navigation";
import { isDemoLoginEnabled } from "@/lib/ui-only";
import { LoginRoute } from "@/components/LoginRoute";

/**
 * Server Component gate: makes `/login` genuinely absent (404) in a
 * production build rather than merely hiding the client UI (#901). See
 * `isDemoLoginEnabled` for the environment logic.
 */
export default function LoginPage() {
  if (!isDemoLoginEnabled()) {
    notFound();
  }

  return <LoginRoute />;
}
