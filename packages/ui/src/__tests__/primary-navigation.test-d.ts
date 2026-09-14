/**
 * Type test for #1903: `NavigationDestination.icon` must carry the
 * name-vs-glyph distinction in the type system. A raw arbitrary string was
 * exactly the defect — the demo passed the icon *keys* "decisions" and
 * "analytics" and the nav rendered them as English words. The compiler, not a
 * runtime guard, is what keeps that from recurring.
 */
import { describe, expectTypeOf, it } from "vitest";

import type { NavigationDestination } from "../primary-navigation";

describe("NavigationDestination.icon", () => {
  it("accepts a known destination icon name", () => {
    expectTypeOf({
      href: "/decisions",
      label: "Quyết định",
      icon: "decisions" as const,
    }).toExtend<NavigationDestination>();
  });

  it("accepts an explicit glyph", () => {
    expectTypeOf({
      href: "/",
      label: "Trang chủ",
      icon: { glyph: "⌂" },
    }).toExtend<NavigationDestination>();
  });

  it("rejects an arbitrary raw string", () => {
    const invalid = {
      href: "/decisions",
      label: "Quyết định",
      // The W6 defect: an icon key the map does not know, rendered as text.
      icon: "some-arbitrary-key" as const,
    };

    // @ts-expect-error — a raw string that is not a DestinationIconName must not compile
    expectTypeOf(invalid).toExtend<NavigationDestination>();
  });
});
