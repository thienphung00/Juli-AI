/**
 * #901 — the demo login screen (and its placeholder-token
 * `loginAsReviewer` helper) must be unreachable in a genuine production
 * build, and unaffected everywhere else: local dev/test, and the App
 * Review build (`NEXT_PUBLIC_UI_ONLY=1`, see
 * infra/scripts/build-frontend-review.sh, which asserts the login screen
 * ships there).
 */
import { notFound } from "next/navigation";
import * as uiOnly from "@/lib/ui-only";
import { LoginRoute } from "@/components/LoginRoute";
import LoginPage from "@/app/login/page";

describe("isDemoLoginEnabled", () => {
  it("is disabled for a genuine production build", () => {
    expect(
      uiOnly.isDemoLoginEnabled({
        NODE_ENV: "production",
        NEXT_PUBLIC_UI_ONLY: undefined,
      })
    ).toBe(false);
  });

  it("stays enabled in local development", () => {
    expect(uiOnly.isDemoLoginEnabled({ NODE_ENV: "development" })).toBe(true);
  });

  it("stays enabled under test", () => {
    expect(uiOnly.isDemoLoginEnabled({ NODE_ENV: "test" })).toBe(true);
  });

  it("stays enabled in the App Review build (NEXT_PUBLIC_UI_ONLY=1 opt-in, even with NODE_ENV=production)", () => {
    expect(
      uiOnly.isDemoLoginEnabled({
        NODE_ENV: "production",
        NEXT_PUBLIC_UI_ONLY: "1",
      })
    ).toBe(true);
  });
});

describe("/login route", () => {
  afterEach(() => {
    jest.mocked(notFound).mockClear();
    jest.restoreAllMocks();
  });

  it("renders the client login route when enabled (dev/test/App Review)", () => {
    jest.spyOn(uiOnly, "isDemoLoginEnabled").mockReturnValue(true);

    const result = LoginPage();

    expect(notFound).not.toHaveBeenCalled();
    expect(result).toEqual(<LoginRoute />);
  });

  it("is unreachable — calls notFound() — when the environment is production", () => {
    jest.spyOn(uiOnly, "isDemoLoginEnabled").mockReturnValue(false);

    expect(() => LoginPage()).toThrow("NEXT_NOT_FOUND");
    expect(notFound).toHaveBeenCalledTimes(1);
  });
});
