// The TikTok pack's fixed configuration: the Seller Center origin and the two create pages the
// Connector fills. On TikTok the Connector only fills forms for actions with no TikTok write
// endpoint (voucher, bundle Deal); it has no readers and never presses the publish button.

export const PLATFORM_ID = "tiktok";
export const PLATFORM_NAME = "TikTok";
export const SELLER_CENTER_ORIGIN = "https://seller-vn.tiktok.com";
/** The host match patterns the Connector asks for after a TikTok pairing (manifest `optional_host_permissions`). */
export const SELLER_CENTER_HOSTS = [`${SELLER_CENTER_ORIGIN}/*`] as const;

/** The fill-job pages, by the pack's PageKind (the form map's key is the job's action). */
export const FILL_JOB_PAGES = {
  voucher: /^\/promotion\/marketing-tools\/voucher\/create\/?$/,
  bundle: /^\/promotion\/marketing-tools\/bundle-deal\/create\/?$/,
} as const;
