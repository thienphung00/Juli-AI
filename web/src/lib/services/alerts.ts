import {
  getMockWorkspaceAlerts,
  type WorkspaceAlert,
} from "@/lib/mock-data/alerts";
import { isUiOnly } from "@/lib/ui-only";
import type { WorkspaceMode } from "@/lib/workspace-mode";

export type { WorkspaceAlert } from "@/lib/mock-data/alerts";

export async function getWorkspaceAlerts(mode: WorkspaceMode): Promise<WorkspaceAlert[]> {
  if (isUiOnly) {
    return getMockWorkspaceAlerts(mode);
  }

  return [];
}
