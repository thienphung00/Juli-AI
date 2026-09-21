import { createTikTokRelayRoute } from "@juli/tiktok-events/server";

import { SITE_ORIGINS } from "../../../../lib/site";

// The handler reads request headers and calls out to TikTok, so it can neither
// be prerendered nor run on the edge (the access token is a Node-process env
// var, deliberately not a NEXT_PUBLIC_* value).
export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export const POST = createTikTokRelayRoute({ allowedOrigins: SITE_ORIGINS });
