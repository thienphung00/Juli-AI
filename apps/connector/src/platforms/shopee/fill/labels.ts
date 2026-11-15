// The Shopee pack's on-page texts: the platform as the seller says it, in the core panels.

import { BANNER_NOT_FOUND, type PanelLabels, panelLabels } from "../../../core/fill/panel";
import { JOB_LABELS } from "./forms";

export const PLATFORM_NAME = "Shopee";
export const PANEL_LABELS: PanelLabels = panelLabels(PLATFORM_NAME);
export const BANNER_FILLED = PANEL_LABELS.filled;
export const BANNER_PAGE_ONLY = PANEL_LABELS.pageOnly;
export { BANNER_NOT_FOUND, JOB_LABELS };
