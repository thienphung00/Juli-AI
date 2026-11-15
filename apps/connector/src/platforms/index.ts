// The platform packs this build carries, in pairing order. The first one keeps the unprefixed
// (pre-0.3.21) storage scope, so an install paired before the split keeps its state as it is.
// A new platform adds its pack here (platforms/<id>/pack.ts) and nothing in core/.

import { createRegistry, type PlatformPack, type PlatformRegistry } from "../platform";
import { shopeePack } from "./shopee/pack";

export const PACKS: readonly PlatformPack[] = [shopeePack];

export const registry: PlatformRegistry = createRegistry(PACKS);
