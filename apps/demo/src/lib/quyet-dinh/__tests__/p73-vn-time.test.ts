import { describe, expect, it } from "vitest";

import { absoluteVn } from "../../../components/reviewer/sandbox-connection-card";
import { confirmedAtLine } from "../../../components/quyet-dinh/do-luong-panel";
import { parseServerIso } from "../../vn-format";
import { vnDate, vnTime } from "../timeline";

describe("P73 server timestamps render in UTC+7", () => {
  it("09:12Z is 16:12 on 27/10/2026", () => {
    expect(confirmedAtLine("2026-10-27T09:12:20Z")).toBe("TikTok xác nhận lúc 16:12 27/10/2026");
  });

  it("an offset-less server string is UTC, not browser-local", () => {
    expect(confirmedAtLine("2026-10-27T09:12:20")).toBe("TikTok xác nhận lúc 16:12 27/10/2026");
    expect(confirmedAtLine("2026-10-27T09:12:20.123456")).toBe("TikTok xác nhận lúc 16:12 27/10/2026");
    expect(vnTime("2026-10-27T09:12:20")).toBe("16:12:20");
  });

  it("crosses midnight into the next Vietnamese day", () => {
    expect(vnDate("2026-10-27T18:30:00Z")).toBe("28/10/2026");
  });

  it("an explicit offset is respected", () => {
    expect(parseServerIso("2026-10-27T16:12:00+07:00")).toBe(Date.parse("2026-10-27T09:12:00Z"));
  });

  it("the connection card time matches", () => {
    expect(absoluteVn("2026-10-27T09:12:00")).toContain("16:12");
    expect(absoluteVn("2026-10-27T09:12:00Z")).toContain("16:12");
  });
});
