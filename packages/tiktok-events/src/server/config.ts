export const ACCESS_TOKEN_ENV = "TIKTOK_EVENTS_API_ACCESS_TOKEN";
export const TEST_EVENT_CODE_ENV = "TIKTOK_EVENTS_API_TEST_EVENT_CODE";

export interface TikTokServerConfig {
  accessToken: string;
  /**
   * Routes events to Events Manager's Test Events tab instead of reporting,
   * for verifying a deploy without polluting live conversions. Unset in
   * production.
   */
  testEventCode?: string;
}

/**
 * Read the Events API credentials from the process environment.
 *
 * Returns null when the token is absent, and the caller turns that into a
 * loud 503 rather than a quiet no-op. That distinction matters here more than
 * usual: the frontend deploy lanes start their candidate with no
 * `EnvironmentFile` unless one is passed explicitly, so "token missing" is a
 * failure mode a deploy can actually produce, and one that would otherwise
 * look exactly like "nobody converted today".
 */
export function readTikTokServerConfig(
  env: Record<string, string | undefined> = process.env,
): TikTokServerConfig | null {
  const accessToken = env[ACCESS_TOKEN_ENV]?.trim();

  if (!accessToken) {
    return null;
  }

  const testEventCode = env[TEST_EVENT_CODE_ENV]?.trim();

  return testEventCode ? { accessToken, testEventCode } : { accessToken };
}
