import { NextResponse, type NextRequest } from "next/server";

/**
 * Juli Ops host split (P16, D25.1).
 *
 * - On the ops host (`ops.app-juli.com`, or any host starting `ops.`) only the
 *   ops pages are served: `/` → `/ops`, any seller page → 404.
 * - Every response on every host carries `X-Robots-Tag: noindex, nofollow`
 *   (D43.5: neither the demo nor ops may be indexed; next.config.ts sets the
 *   same header on the paths this middleware does not match).
 * - On every other public host (`demo.app-juli.com`, `app.app-juli.com`) `/ops/*` is a 404.
 * - Local hosts (localhost / 127.0.0.1, dev and e2e) serve both.
 *
 * No cookie is set here, and the app keeps its session in localStorage, which
 * is per origin: the ops host's sign-in is never shared with the seller host
 * (host-only by construction; no `Domain=` cookie exists).
 */

const LOCAL_HOSTS = new Set(["localhost", "127.0.0.1", "[::1]"]);

export function hostKind(hostHeader: string | null): "ops" | "local" | "seller" {
  const host = (hostHeader ?? "").toLowerCase().replace(/:\d+$/, "");
  if (host.startsWith("ops.")) return "ops";
  if (LOCAL_HOSTS.has(host)) return "local";
  return "seller";
}

export function isOpsPath(pathname: string): boolean {
  return pathname === "/ops" || pathname.startsWith("/ops/");
}

/** The demo and ops hosts are never indexed (D43.5). Shared with next.config.ts. */
export const ROBOTS_HEADER = { name: "X-Robots-Tag", value: "noindex, nofollow" } as const;

function noindex(response: NextResponse): NextResponse {
  response.headers.set(ROBOTS_HEADER.name, ROBOTS_HEADER.value);
  return response;
}

function notFound(): NextResponse {
  return new NextResponse("Not found", { status: 404, headers: { "Content-Type": "text/plain; charset=utf-8" } });
}

export function middleware(request: NextRequest): NextResponse {
  const kind = hostKind(request.headers.get("host"));
  const { pathname } = request.nextUrl;
  if (kind === "ops") {
    if (pathname === "/") {
      const url = request.nextUrl.clone();
      url.pathname = "/ops";
      return noindex(NextResponse.redirect(url));
    }
    if (!isOpsPath(pathname)) {
      return noindex(notFound());
    }
    return noindex(NextResponse.next());
  }
  if (kind === "seller" && isOpsPath(pathname)) {
    return noindex(notFound());
  }
  return noindex(NextResponse.next());
}

export const config = {
  // Pages only: static assets, the Next runtime and the API proxy pass through.
  matcher: ["/((?!_next/|v1/|api/|favicon|.*\\.(?:png|jpg|jpeg|svg|ico|webp|woff2?|txt|xml)$).*)"],
};
