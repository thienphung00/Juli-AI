/**
 * The id of the pixel's <script>. Its own module (and package subpath
 * `@juli/tiktok-events/pixel-id`) so a consent banner can check "is the pixel
 * loaded?" without bundling the pixel snippet (landing P33-A, unused JS).
 */
export const TIKTOK_PIXEL_SCRIPT_ID = "tiktok-pixel";
