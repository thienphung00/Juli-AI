import { createTikTokRelayRoute } from "@juli/tiktok-events/server";

import { SITE_ORIGINS } from "../../../../lib/site-origins";

// See apps/landing's copy: dynamic and Node, because this reads request
// headers and holds the Events API access token.
export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export const POST = createTikTokRelayRoute({ allowedOrigins: SITE_ORIGINS });
