import type { ReactNode } from "react";

export interface PageHeaderProps {
  title: string;
  subtitle?: string;
  shopName?: string;
  shopStatus?: string;
  trailing?: ReactNode;
}

export function PageHeader({
  title,
  subtitle,
  shopName,
  shopStatus,
  trailing,
}: PageHeaderProps) {
  return (
    <header className="juli-page-header" role="banner">
      <div className="juli-page-header__content">
        <div className="juli-page-header__titles">
          <h1 className="juli-page-header__title">{title}</h1>
          {shopName ? (
            <p className="juli-page-header__shop">
              <span className="juli-page-header__shop-name">{shopName}</span>
              {shopStatus ? (
                <span className="juli-page-header__shop-status">{shopStatus}</span>
              ) : null}
            </p>
          ) : subtitle ? (
            <p className="juli-page-header__subtitle">{subtitle}</p>
          ) : null}
        </div>
        {trailing ? (
          <div className="juli-page-header__trailing">{trailing}</div>
        ) : null}
      </div>
    </header>
  );
}
