import Link from "next/link";

import { LOGIN_URL, SIGNUP_URL } from "../../lib/site";
import { BrandMark } from "./brand";
import { LinkButton } from "./button";
import { HeaderMenu, HeaderNav } from "./header-nav";
import { Icon } from "./icon";

export interface SiteHeaderProps {
  /**
   * `default` every page · `signup` (`/dang-ky`, Signup.dc.html): logo +
   * "Đã có tài khoản? Đăng nhập" only, no nav, no trial CTA.
   */
  variant?: "default" | "signup";
  /** Force the active nav item's path (tests); normally read from the router. */
  pathname?: string;
}

/**
 * Site header (D44, Main.dc.html). Desktop: logo · nav · "Đăng nhập" ·
 * dark "Dùng thử miễn phí". Below 900 px: logo · "Dùng thử" · menu button
 * (a `<details>` panel with the same nav + "Đăng nhập" + "Liên hệ").
 * The header has no headings (seo README rule 4).
 */
export function SiteHeader({ variant = "default", pathname }: SiteHeaderProps) {
  if (variant === "signup") {
    return (
      <header className="ui-header">
        <div className="ui-header__inner ui-container">
          <Link aria-label="Juli AI, trang chủ" className="ui-header__brand" href="/">
            <BrandMark />
          </Link>
          <span className="ui-header__spacer" />
          <a className="ui-header__login ui-header__login--always" data-testid="header-login-link" href={LOGIN_URL}>
            Đã có tài khoản? Đăng nhập
          </a>
        </div>
      </header>
    );
  }

  return (
    <header className="ui-header">
      <div className="ui-header__inner ui-container">
        <Link aria-label="Juli AI, trang chủ" className="ui-header__brand" href="/">
          <BrandMark />
        </Link>
        <HeaderNav className="ui-header__nav" label="Điều hướng chính" pathname={pathname} />
        <div className="ui-header__actions">
          <a className="ui-header__login" data-testid="header-login-link" href={LOGIN_URL}>
            Đăng nhập
          </a>
          <LinkButton data-testid="header-trial-cta" href={SIGNUP_URL} size="md">
            Dùng thử<span className="ui-header__cta-long"> miễn phí</span>
          </LinkButton>
          <HeaderMenu>
            <summary aria-label="Menu" className="ui-header__menu-button">
              <Icon className="ui-header__menu-open" name="menu" />
              <Icon className="ui-header__menu-close" name="close" />
            </summary>
            <div className="ui-header__panel">
              <HeaderNav className="ui-header__panel-nav" label="Menu trên điện thoại" pathname={pathname} />
              <div className="ui-header__panel-extra">
                <Link className="ui-header__link" href="/contact">
                  Liên hệ
                </Link>
                <a className="ui-header__link" data-testid="menu-login-link" href={LOGIN_URL}>
                  Đăng nhập
                </a>
              </div>
            </div>
          </HeaderMenu>
        </div>
      </div>
    </header>
  );
}
