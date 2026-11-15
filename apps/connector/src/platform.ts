// The one interface between the platform-free Connector core (src/core/) and a platform pack
// (src/platforms/<id>/), and the registry of the packs one build carries (T11, 2026-11-15).
//
// The core never imports a pack: it is handed one (or the registry) by the composition roots
// (the service worker and the content scripts). A pack is plain data plus pure functions; the
// pairing token alone says which shop and which platform a pairing is (`TokenInfo.platform` is a
// pack id).

import type { CoreJob, FormMap } from "./core/fill/form";
import type { JobLabels } from "./core/fill/job-panel";
import type { PanelLabels } from "./core/fill/panel";

/** What a page of a platform is, in the pack's own words (e.g. a report page or an action's form). */
export type PageKind = string;

/** One answer the page itself received (the page hook sees it). */
export interface PageAnswer {
  method: string;
  /** The answer's URL path (no origin, no query). */
  pathname: string;
  body: unknown;
}

/** The person saved the form the Connector filled: the new object's platform id (digits only). */
export interface SaveResult {
  ref: string;
}

/** One read-only reader of a platform's own report pages (a pack may have none). */
export interface Reader {
  id: string;
  /** The gateway datasets it posts. */
  datasets: readonly string[];
  /** The build-time switch: an inactive reader is never planned. */
  active: boolean;
}

/** The pack's texts, in the seller's own words. */
export interface PackLabels {
  /** The platform as the seller says it ("Shopee"). */
  name: string;
  /** The listing fill panel's banners that name the platform. */
  panel: PanelLabels;
  /** The fill-job panel's texts that name the platform. */
  job: JobLabels;
}

export interface PlatformPack<J extends CoreJob = CoreJob> {
  /** The gateway's platform name, the pairing token's `platform`. */
  id: string;
  /** The seller centre origin the fill-job pages open on. */
  origin: string;
  /** Host match patterns the Connector holds for this platform (manifest `host_permissions`). */
  hosts: readonly string[];
  /** Host match patterns requested only when a shop of this platform is paired (`optional_host_permissions`). */
  optionalHosts: readonly string[];
  /** The kind of one of the platform's pages, or null when the URL is not the platform's. */
  recognise(url: string): PageKind | null;
  /** The platform shop id the page is signed in to, or null when the page does not say. */
  shopOnPage(doc: Document): string | null;
  /** The read-only readers (none for a pack that only fills forms). */
  readers: readonly Reader[];
  /** Per fill-job action: the form's page and its filler. */
  forms: Readonly<Record<string, FormMap<J>>>;
  /** One fill job as Juli serves it, validated (its page must be the action's form), or null. */
  parseJob(raw: unknown): J | null;
  /** The page's own answer to the person's save of a filled form, or null when it is not one. */
  savedSignal(page: PageAnswer): SaveResult | null;
  labels: PackLabels;
}

export interface PlatformRegistry {
  /** The packs, in pairing order (a pairing code is offered to each until one platform takes it). */
  readonly packs: readonly PlatformPack[];
  /** The pack whose storage scope is the unprefixed (pre-0.3.21) one: the first registered. */
  readonly legacy: PlatformPack;
  get(id: string | undefined): PlatformPack | undefined;
  /** The pack one of whose pages `url` is. */
  forUrl(url: string): PlatformPack | undefined;
}

export function createRegistry(packs: readonly PlatformPack[]): PlatformRegistry {
  const first = packs[0];
  if (!first) throw new Error("no platform pack");
  const byId = new Map<string, PlatformPack>();
  for (const pack of packs) {
    if (byId.has(pack.id)) throw new Error(`duplicate platform pack ${pack.id}`);
    byId.set(pack.id, pack);
  }
  return {
    packs,
    legacy: first,
    get: (id) => (id === undefined ? undefined : byId.get(id)),
    forUrl: (url) => packs.find((pack) => pack.recognise(url) !== null),
  };
}

/** The pack's readers that are switched on. */
export function activeReaders(pack: Pick<PlatformPack, "readers">): Reader[] {
  return pack.readers.filter((reader) => reader.active);
}
