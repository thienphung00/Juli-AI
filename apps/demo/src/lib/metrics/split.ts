import { streamShortName, channelName } from "../platform-labels";
import type { SplitChannel } from "../shopee-analytics/types";

/** The three channels of the profit split, in display order (Track P / decision #46). */
export const SPLIT_CHANNEL_ORDER: readonly SplitChannel[] = ["organic", "ads", "affiliate"];

/** Organic / Quảng cáo / TTLK (names from the platform table, never typed again on a screen). */
export function splitChannelName(ch: SplitChannel): string {
  return ch === "affiliate" ? streamShortName("shopee", "affiliate") : channelName("shopee", ch);
}
