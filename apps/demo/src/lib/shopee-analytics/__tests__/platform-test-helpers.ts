import type { NavPlatform } from "../../app-navigation";
import { probeShopPlatform } from "../platform";

/**
 * Test-only: make `shops/me` answer `platform` for a shop through the module's public read, so the answer is
 * cached the way a real one is. The cache has no reset: give each test its own shop id.
 */
export async function seedShopPlatform(shopId: string, platform: NavPlatform): Promise<void> {
  const fetchImpl = (async () => new Response(JSON.stringify({ platform }), { status: 200 })) as unknown as typeof fetch;
  await probeShopPlatform("seed", shopId, fetchImpl);
}
