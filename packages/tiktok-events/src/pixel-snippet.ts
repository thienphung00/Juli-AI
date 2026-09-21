/**
 * A data source id is 20 uppercase alphanumerics today, but the guard is
 * deliberately a shape check rather than a length check: this string is
 * interpolated into JavaScript that is injected with
 * `dangerouslySetInnerHTML`, so a value containing a quote or `</script>`
 * would break out of the snippet. The id is a literal in `data-source.ts` and
 * so cannot be attacker-controlled today — this is what keeps that true if it
 * ever becomes configurable.
 */
const DATA_SOURCE_ID_PATTERN = /^[A-Z0-9]{8,40}$/;

/**
 * TikTok's base pixel code, verbatim, with the data source id substituted.
 *
 * The body between `!function` and `}(window, document, 'ttq')` is copied
 * unchanged from TikTok's Events Manager install step and must stay that way —
 * it is a vendor loader, not Juli code, and reformatting it (a stray
 * Prettier pass, a "tidy" of the minification) is how a pixel silently stops
 * loading. Only the two calls at the end are ours.
 *
 * What it does, so nobody has to read the minified form: it defines
 * `window.ttq` as a queue that records `page`/`track`/`identify`/... calls
 * synchronously, then appends the real `events.js`. Calls made before that
 * script arrives are replayed once it does — which is why `track()` can be
 * invoked from a component that mounts immediately, with no readiness check.
 */
export function tiktokPixelSnippet(dataSourceId: string): string {
  if (!DATA_SOURCE_ID_PATTERN.test(dataSourceId)) {
    throw new Error(
      "tiktokPixelSnippet: data source id must be uppercase alphanumeric",
    );
  }

  return `!function (w, d, t) {
  w.TiktokAnalyticsObject=t;var ttq=w[t]=w[t]||[];ttq.methods=["page","track","identify","instances","debug","on","off","once","ready","alias","group","enableCookie","disableCookie","holdConsent","revokeConsent","grantConsent"],ttq.setAndDefer=function(t,e){t[e]=function(){t.push([e].concat(Array.prototype.slice.call(arguments,0)))}};for(var i=0;i<ttq.methods.length;i++)ttq.setAndDefer(ttq,ttq.methods[i]);ttq.instance=function(t){for(
var e=ttq._i[t]||[],n=0;n<ttq.methods.length;n++)ttq.setAndDefer(e,ttq.methods[n]);return e},ttq.load=function(e,n){var r="https://analytics.tiktok.com/i18n/pixel/events.js",o=n&&n.partner;ttq._i=ttq._i||{},ttq._i[e]=[],ttq._i[e]._u=r,ttq._t=ttq._t||{},ttq._t[e]=+new Date,ttq._o=ttq._o||{},ttq._o[e]=n||{};n=document.createElement("script")
;n.type="text/javascript",n.async=!0,n.src=r+"?sdkid="+e+"&lib="+t;e=document.getElementsByTagName("script")[0];e.parentNode.insertBefore(n,e)};


  ttq.load('${dataSourceId}');
  ttq.page();
}(window, document, 'ttq');`;
}
