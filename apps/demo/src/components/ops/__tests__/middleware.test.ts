import { NextRequest } from "next/server";
import { describe, expect, it } from "vitest";

import { hostKind, middleware } from "../../../middleware";

function req(host: string, path: string) {
  return new NextRequest(`http://${host}${path}`, { headers: { host } });
}

describe("ops host middleware (D25.1)", () => {
  it("classifies hosts", () => {
    expect(hostKind("ops.app-juli.com")).toBe("ops");
    expect(hostKind("demo.app-juli.com")).toBe("seller");
    expect(hostKind("127.0.0.1:3326")).toBe("local");
  });
  it("ops host: / → /ops, seller pages 404, noindex everywhere", () => {
    const root = middleware(req("ops.app-juli.com", "/"));
    expect(root.status).toBe(307);
    expect(root.headers.get("location")).toBe("http://ops.app-juli.com/ops");
    expect(middleware(req("ops.app-juli.com", "/decisions")).status).toBe(404);
    const ops = middleware(req("ops.app-juli.com", "/ops/shops/x"));
    expect(ops.status).toBe(200);
    expect(ops.headers.get("X-Robots-Tag")).toBe("noindex, nofollow");
    expect(ops.headers.get("set-cookie")).toBeNull();
  });
  it("seller host: /ops is a 404, seller pages pass", () => {
    expect(middleware(req("demo.app-juli.com", "/ops")).status).toBe(404);
    expect(middleware(req("demo.app-juli.com", "/decisions")).status).toBe(200);
  });
});
