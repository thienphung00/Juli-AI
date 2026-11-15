// The gateway client bound to the Shopee pack: the core IngestClient with platform "shopee".

import { IngestClient } from "../../../core/ingest/client";
import { PLATFORM_ID } from "../config";

export { GatewayError, ingestBody, type IngestBody, type TokenInfo } from "../../../core/ingest/client";

type FetchLike = (input: string, init?: RequestInit) => Promise<Response>;

export class GatewayClient extends IngestClient {
  constructor(fetchImpl?: FetchLike, origin?: string) {
    super(PLATFORM_ID, fetchImpl, origin);
  }
}
