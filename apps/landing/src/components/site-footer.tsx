import { JuliLogo } from "@juli/brand";

import { DEMO_URL, SECTION_IDS } from "../lib/site";

export function SiteFooter() {
  return (
    <footer className="lp-footer" id={SECTION_IDS.contact}>
      <div className="lp-footer__brand">
        <JuliLogo size={26} />
        <p className="lp-footer__tagline">Trợ lý AI cho người bán TikTok Shop</p>
        <p className="lp-footer__partner">TikTok Shop Partner ✓</p>
      </div>
      <nav aria-label="Liên kết chân trang" className="lp-footer__nav">
        <a className="lp-footer__link" href={DEMO_URL}>
          Trải nghiệm Demo
        </a>
        <a className="lp-footer__link" href={`#${SECTION_IDS.features}`}>
          Tính năng
        </a>
        <a className="lp-footer__link" href={`#${SECTION_IDS.comparison}`}>
          Giải pháp
        </a>
        <a className="lp-footer__link" href="mailto:lienhe@app-juli.com">
          lienhe@app-juli.com
        </a>
      </nav>
      <p className="lp-footer__legal">© 2026 Juli AI</p>
    </footer>
  );
}
