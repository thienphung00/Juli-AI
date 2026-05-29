import { filterTrendsMock, type TrendsResults, type TrendsTab } from "@/lib/mock-data/trends";
import { isUiOnly } from "@/lib/ui-only";
import type { WorkspaceMode } from "@/lib/workspace-mode";

export interface GetTrendsParams {
  mode: WorkspaceMode;
  tab: TrendsTab;
  query?: string;
}

export async function getTrends({
  mode,
  tab,
  query = "",
}: GetTrendsParams): Promise<TrendsResults> {
  if (isUiOnly) {
    return filterTrendsMock(mode, tab, query);
  }

  // v1.5: wire to GET /v1/trends/* and /v1/products?trending=true
  return filterTrendsMock(mode, tab, query);
}
