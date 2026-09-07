import { beforeEach, describe, expect, it } from "vitest";

import {
  ENTRY_MODE_STORAGE_KEY,
  readEntryMode,
  writeEntryMode,
} from "../entry-mode";

describe("entry-mode", () => {
  beforeEach(() => {
    window.sessionStorage.clear();
  });

  it("defaults to unset when nothing is stored", () => {
    expect(readEntryMode()).toBe("unset");
  });

  it("persists the replay choice under a dedicated storage key", () => {
    writeEntryMode("replay");

    expect(window.sessionStorage.getItem(ENTRY_MODE_STORAGE_KEY)).toBe(
      "replay",
    );
    expect(readEntryMode()).toBe("replay");
  });

  it("ignores an unrecognized stored value rather than trusting it blindly", () => {
    window.sessionStorage.setItem(ENTRY_MODE_STORAGE_KEY, "tampered");

    expect(readEntryMode()).toBe("unset");
  });

  it("never shares its storage key with the mock-state or mode keys it sits beside", () => {
    expect(ENTRY_MODE_STORAGE_KEY).not.toBe("juli_demo_mode");
    expect(ENTRY_MODE_STORAGE_KEY).not.toBe("juli_demo_mutable_state");
  });
});
