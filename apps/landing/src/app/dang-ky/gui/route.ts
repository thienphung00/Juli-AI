import { relaySignup } from "../../../components/signup/signup-relay";
import { SITE_ORIGINS } from "../../../lib/site";

// Reads the request and calls the Juli API with a server-only key: never
// prerendered, Node runtime (the env vars are process env, not NEXT_PUBLIC_*).
export const dynamic = "force-dynamic";
export const runtime = "nodejs";

/** `POST /dang-ky/gui` — the trial sign-up form's target (P33-F). */
export async function POST(request: Request): Promise<Response> {
  return relaySignup(request, {
    allowedOrigins: SITE_ORIGINS,
    env: {
      apiUrl: process.env.TRIAL_SIGNUP_API_URL,
      relayKey: process.env.TRIAL_SIGNUP_RELAY_KEY,
    },
  });
}
