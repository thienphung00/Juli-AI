import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CAP_PT_LUONG, CAP_PT_LUONG_MOBILE, CAP_PT_PHEU } from "../components/product/screens";
import {
  Breadcrumb,
  Button,
  Card,
  CheckList,
  Eyebrow,
  FaqList,
  FeatureRow,
  FunnelDiagram,
  Heading,
  Icon,
  ICON_NAMES,
  LinkButton,
  LOOP_STEPS,
  Section,
  SectionIntro,
  Shot,
  ShotFrame,
  SiteFooter,
  SiteHeader,
  StatusPill,
  StepList,
  TextLink,
  TocNav,
} from "../components/ui";
import { isActiveNav } from "../components/ui/header-nav";
import { COMPANY, DEMO_URL, LOGIN_URL, PRODUCT_MENU, SIGNUP_URL } from "../lib/site";

const SHOT = { variants: CAP_PT_LUONG, alt: "GMV theo 5 luồng (dữ liệu mẫu)" };

describe("SiteHeader", () => {
  it("has the D44 nav, 'Đăng nhập' and the dark trial button", () => {
    render(<SiteHeader pathname="/" />);
    const nav = screen.getByRole("navigation", { name: "Điều hướng chính" });
    // "Sản phẩm" is a dropdown button (D46.1); its 4 links come first in the DOM.
    expect(within(nav).getByRole("button", { name: "Sản phẩm" })).toHaveAttribute("aria-expanded", "false");
    expect(within(nav).getAllByRole("link").map((a) => a.getAttribute("href"))).toEqual([
      ...PRODUCT_MENU.map((item) => item.href),
      "/ket-noi/tiktok-shop",
      "/blog",
      "/about",
    ]);
    expect(screen.getByTestId("header-login-link")).toHaveAttribute("href", LOGIN_URL);
    const trial = screen.getByTestId("header-trial-cta");
    expect(trial).toHaveAttribute("href", SIGNUP_URL);
    expect(trial).toHaveClass("ui-button", "ui-button--primary");
    expect(trial).toHaveTextContent("Dùng thử miễn phí");
  });

  it("marks the current section with aria-current, including sub-pages", () => {
    render(<SiteHeader pathname="/san-pham/phan-tich-shop" />);
    const nav = screen.getByRole("navigation", { name: "Điều hướng chính" });
    // The "Sản phẩm" button lights up on every /san-pham/* page; the exact page link carries aria-current.
    expect(within(nav).getByRole("button", { name: "Sản phẩm" })).toHaveAttribute("data-active");
    expect(within(nav).getByRole("link", { name: /^Phân tích shop/ })).toHaveAttribute("aria-current", "page");
    expect(within(nav).getByRole("link", { name: /^Tổng quan sản phẩm/ })).not.toHaveAttribute("aria-current");
    expect(within(nav).getByRole("link", { name: "Blog" })).not.toHaveAttribute("aria-current");
    render(<SiteHeader pathname="/ket-noi/tiktok-shop" />);
    const navs = screen.getAllByRole("navigation", { name: "Điều hướng chính" });
    expect(within(navs[1]).getByRole("button", { name: "Sản phẩm" })).not.toHaveAttribute("data-active");
    expect(within(navs[1]).getByRole("link", { name: "Kết nối TikTok Shop" })).toHaveAttribute("aria-current", "page");
  });

  it("isActiveNav matches the path and its children only", () => {
    expect(isActiveNav("/blog", "/blog")).toBe(true);
    expect(isActiveNav("/blog/abc", "/blog")).toBe(true);
    expect(isActiveNav("/blogger", "/blog")).toBe(false);
    expect(isActiveNav(null, "/blog")).toBe(false);
  });

  it("mobile menu is a <details> disclosure with nav, contact and sign-in", () => {
    const { container } = render(<SiteHeader />);
    const menu = container.querySelector("details.ui-header__menu");
    expect(menu).not.toBeNull();
    expect(within(menu as HTMLElement).getByLabelText("Menu").tagName).toBe("SUMMARY");
    expect(within(menu as HTMLElement).getByRole("link", { name: "Liên hệ" })).toHaveAttribute("href", "/contact");
    expect(screen.getByTestId("menu-login-link")).toHaveAttribute("href", LOGIN_URL);
  });

  it("product dropdown (D46.1): disclosure button, 4 described links in the DOM while closed", () => {
    render(<SiteHeader pathname="/" />);
    const nav = screen.getByRole("navigation", { name: "Điều hướng chính" });
    const button = within(nav).getByRole("button", { name: "Sản phẩm" });
    const panel = document.getElementById(button.getAttribute("aria-controls") ?? "");
    expect(panel).not.toBeNull();
    expect(nav).toContainElement(panel);
    // Closed: links are rendered (crawlable), the panel is hidden by CSS via [data-open].
    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(button.closest(".ui-navmenu")).not.toHaveAttribute("data-open");
    const links = within(panel as HTMLElement).getAllByRole("link");
    expect(links.map((a) => a.getAttribute("href"))).toEqual(PRODUCT_MENU.map((item) => item.href));
    PRODUCT_MENU.forEach((item, index) => {
      expect(links[index]).toHaveTextContent(item.label);
      expect(links[index]).toHaveTextContent(item.description);
      expect(item.description.split(/\s+/).length, item.description).toBeLessThanOrEqual(8);
    });
    expect(links[0]).toHaveTextContent("Tổng quan sản phẩm");
  });

  it("product dropdown opens on click, closes on a second click, Escape (focus back) and click outside", () => {
    render(<SiteHeader pathname="/" />);
    const nav = screen.getByRole("navigation", { name: "Điều hướng chính" });
    const button = within(nav).getByRole("button", { name: "Sản phẩm" });
    const root = button.closest(".ui-navmenu") as HTMLElement;

    fireEvent.click(button);
    expect(button).toHaveAttribute("aria-expanded", "true");
    expect(root).toHaveAttribute("data-open");
    fireEvent.click(button);
    expect(button).toHaveAttribute("aria-expanded", "false");

    fireEvent.click(button);
    const first = within(root).getAllByRole("link")[0];
    first.focus();
    fireEvent.keyDown(first, { key: "Escape" });
    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(document.activeElement).toBe(button);

    fireEvent.click(button);
    expect(button).toHaveAttribute("aria-expanded", "true");
    fireEvent.pointerDown(document.body);
    expect(button).toHaveAttribute("aria-expanded", "false");

    // Focus leaving the desktop panel (Tab past the last item) closes it.
    fireEvent.click(button);
    fireEvent.blur(button, { relatedTarget: within(nav).getByRole("link", { name: "Blog" }) });
    expect(button).toHaveAttribute("aria-expanded", "false");
  });

  it("product dropdown closes when the route changes", () => {
    const { rerender } = render(<SiteHeader pathname="/" />);
    const button = within(screen.getByRole("navigation", { name: "Điều hướng chính" })).getByRole("button", {
      name: "Sản phẩm",
    });
    fireEvent.click(button);
    expect(button).toHaveAttribute("aria-expanded", "true");
    rerender(<SiteHeader pathname="/san-pham/do-luong-gmv" />);
    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(within(screen.getByRole("navigation", { name: "Điều hướng chính" })).getByRole("link", { name: /^Đo lường GMV/ }))
      .toHaveAttribute("aria-current", "page");
  });

  it("mobile menu shows Sản phẩm as an expandable group with the same 4 links", () => {
    render(<SiteHeader pathname="/" />);
    const nav = screen.getByRole("navigation", { name: "Menu trên điện thoại" });
    const button = within(nav).getByRole("button", { name: "Sản phẩm" });
    expect(button.closest(".ui-navmenu")).toHaveClass("ui-navmenu--panel");
    fireEvent.click(button);
    expect(button).toHaveAttribute("aria-expanded", "true");
    const panel = document.getElementById(button.getAttribute("aria-controls") ?? "") as HTMLElement;
    expect(within(panel).getAllByRole("link").map((a) => a.getAttribute("href"))).toEqual(
      PRODUCT_MENU.map((item) => item.href),
    );
    // Two dropdowns on the page, two distinct panel ids.
    const desktop = within(screen.getByRole("navigation", { name: "Điều hướng chính" })).getByRole("button", {
      name: "Sản phẩm",
    });
    expect(desktop.getAttribute("aria-controls")).not.toBe(button.getAttribute("aria-controls"));
    expect(desktop).toHaveAttribute("aria-expanded", "false");
  });

  it("signup variant: logo + 'Đã có tài khoản? Đăng nhập' only", () => {
    render(<SiteHeader variant="signup" />);
    expect(screen.queryByRole("navigation", { name: "Điều hướng chính" })).toBeNull();
    expect(screen.queryByTestId("header-trial-cta")).toBeNull();
    expect(screen.getByTestId("header-login-link")).toHaveTextContent("Đã có tài khoản? Đăng nhập");
  });

  it("has no headings (seo README rule 4)", () => {
    const { container } = render(<SiteHeader />);
    expect(container.querySelector("h1, h2, h3, h4, h5, h6")).toBeNull();
  });
});

describe("SiteFooter", () => {
  it("names the company with MST, links the three columns, no social links, no headings", () => {
    const { container } = render(<SiteFooter />);
    const footer = screen.getByRole("contentinfo");
    expect(screen.getByTestId("footer-company")).toHaveTextContent(`${COMPANY.name} · MST ${COMPANY.taxId}`);
    const hrefs = within(footer).getAllByRole("link").map((a) => a.getAttribute("href") ?? "");
    for (const href of ["/san-pham", "/ket-noi/tiktok-shop", "/about", "/blog", "/contact", DEMO_URL, "/privacy", "/terms"]) {
      expect(hrefs, href).toContain(href);
    }
    expect(hrefs.join(" ")).not.toMatch(/facebook|tiktok\.com|youtube|zalo|linkedin|instagram/i);
    expect(within(footer).getByRole("button", { name: "Cài đặt cookie" })).toBeInTheDocument();
    expect(container.querySelector("h1, h2, h3, h4, h5, h6")).toBeNull();
  });
});

describe("buttons", () => {
  it("LinkButton: variants + sizes as classes, internal vs external href", () => {
    render(
      <>
        <LinkButton href="/dang-ky">Dùng thử</LinkButton>
        <LinkButton href={DEMO_URL} icon="play" size="md" variant="secondary">
          Xem demo
        </LinkButton>
        <LinkButton blockOnMobile href="/x" variant="on-dark">
          Trắng
        </LinkButton>
      </>,
    );
    expect(screen.getByRole("link", { name: "Dùng thử" })).toHaveClass("ui-button--primary", "ui-button--lg");
    const demo = screen.getByRole("link", { name: "Xem demo" });
    expect(demo).toHaveClass("ui-button--secondary", "ui-button--md");
    expect(demo).toHaveAttribute("href", DEMO_URL);
    expect(demo.querySelector('svg[data-icon="play"]')).toHaveAttribute("aria-hidden", "true");
    expect(screen.getByRole("link", { name: "Trắng" })).toHaveClass("ui-button--on-dark", "ui-button--block-mobile");
  });

  it("Button defaults to type=button; TextLink appends a decorative arrow", () => {
    render(
      <>
        <Button variant="on-dark-secondary">Mở</Button>
        <TextLink href="/san-pham/phan-tich-shop">Xem Phân tích shop</TextLink>
      </>,
    );
    expect(screen.getByRole("button", { name: "Mở" })).toHaveAttribute("type", "button");
    const link = screen.getByRole("link", { name: /Xem Phân tích shop/ });
    expect(link).toHaveAttribute("href", "/san-pham/phan-tich-shop");
    expect(link.querySelector('[aria-hidden="true"]')).toHaveTextContent("→");
  });
});

describe("section primitives", () => {
  it("Section: tone/spacing classes, aria-labelledby, container", () => {
    render(
      <Section labelledBy="gia" spacing="compact" tone="dark">
        <SectionIntro eyebrow="Giá" lead="Không cần thẻ." onDark title="Dùng thử 3 tháng" titleId="gia" />
      </Section>,
    );
    const region = screen.getByRole("region", { name: "Dùng thử 3 tháng" });
    expect(region).toHaveClass("ui-section--dark", "ui-section--compact");
    expect(region.firstElementChild).toHaveClass("ui-container");
    expect(screen.getByRole("heading", { level: 2 })).toHaveClass("ui-heading--section", "ui-heading--on-dark");
    expect(screen.getByText("Giá").tagName).toBe("P");
  });

  it("Heading picks the element by level and the look by size", () => {
    render(
      <>
        <Heading level={1}>Trang chủ</Heading>
        <Heading level={2} size="feature">
          Tính năng
        </Heading>
      </>,
    );
    expect(screen.getByRole("heading", { level: 1 })).toHaveClass("ui-heading--display");
    expect(screen.getByRole("heading", { level: 2 })).toHaveClass("ui-heading--feature");
  });

  it("Eyebrow badge has a decorative dot; Card and CheckList render", () => {
    render(
      <>
        <Eyebrow variant="badge">TikTok Shop Open API</Eyebrow>
        <Card as="article" tone="highlight">
          x
        </Card>
        <CheckList items={["Một", "Hai"]} />
      </>,
    );
    expect(screen.getByText("TikTok Shop Open API").querySelector(".ui-eyebrow__dot")).toHaveAttribute("aria-hidden", "true");
    expect(screen.getByRole("article")).toHaveClass("ui-card--highlight");
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
  });
});

describe("Shot", () => {
  it("frames one image with the default 'Dữ liệu mẫu' caption on a backdrop", () => {
    const { container } = render(<Shot images={SHOT} />);
    const figure = container.querySelector("figure");
    expect(figure).toHaveClass("ui-shot--backdrop", "ui-shot--pad-md");
    expect(within(figure as HTMLElement).getByText("Dữ liệu mẫu").tagName).toBe("FIGCAPTION");
    const img = screen.getByRole("img", { name: SHOT.alt });
    expect(img).toHaveAttribute("width", "1280");
    expect(img).toHaveAttribute("loading", "lazy");
  });

  it("adds browser chrome with a title, a mobile crop <source> with its own size, and a crop ratio", () => {
    const { container } = render(
      <Shot chrome="Phân tích · Juli" images={{ ...SHOT, crop: 4 / 3, mobileVariants: CAP_PT_LUONG_MOBILE }} priority />,
    );
    expect(screen.getByText("Phân tích · Juli")).toBeInTheDocument();
    const mobile = container.querySelectorAll('source[media="(max-width: 640px)"]');
    expect(mobile).toHaveLength(2);
    expect(mobile[0]).toHaveAttribute("width", String(CAP_PT_LUONG_MOBILE[0].width));
    expect(mobile[0]).toHaveAttribute("height", String(CAP_PT_LUONG_MOBILE[0].height));
    expect(container.querySelector(".ui-shot__media--crop")).toHaveStyle({ "--shot-crop": String(4 / 3) });
    expect(screen.getByRole("img", { name: SHOT.alt })).toHaveAttribute("loading", "eager");
  });

  it("stacked = one frame per image; joined = one frame; caption can be custom or hidden", () => {
    const two = [SHOT, { variants: CAP_PT_PHEU, alt: "Phễu (dữ liệu mẫu)" }];
    const { container, rerender } = render(<Shot caption="Dữ liệu mẫu · Cửa hàng Mẫu Hoa Mai" images={two} />);
    expect(container.querySelectorAll(".ui-shot__frame")).toHaveLength(2);
    expect(screen.getByText("Dữ liệu mẫu · Cửa hàng Mẫu Hoa Mai")).toBeInTheDocument();
    rerender(<Shot backdrop={false} caption={null} images={two} layout="joined" />);
    expect(container.querySelectorAll(".ui-shot__frame")).toHaveLength(1);
    expect(container.querySelector("figcaption")).toBeNull();
  });

  it("ShotFrame as a figure puts its caption in a figcaption", () => {
    const { container } = render(<ShotFrame as="figure" caption="Dữ liệu mẫu" elevation="float" images={SHOT} />);
    expect(container.querySelector("figure > figcaption")).toHaveTextContent("Dữ liệu mẫu");
  });
});

describe("content blocks", () => {
  it("FeatureRow: section named by its heading, bullets, link, media; reverse class", () => {
    render(
      <FeatureRow
        bullets={["So 30 ngày"]}
        eyebrow="Phân tích shop"
        link={{ href: "/san-pham/phan-tich-shop", label: "Xem Phân tích shop" }}
        media={<Shot images={SHOT} />}
        reverse
        title="Biết GMV tăng hay giảm vì luồng nào"
        titleId="cap1"
      >
        Juli tách GMV thành 5 luồng.
      </FeatureRow>,
    );
    const region = screen.getByRole("region", { name: "Biết GMV tăng hay giảm vì luồng nào" });
    expect(region).toHaveClass("ui-feature--reverse");
    expect(within(region).getByText("So 30 ngày")).toBeInTheDocument();
    expect(within(region).getByRole("link", { name: /Xem Phân tích shop/ })).toBeInTheDocument();
    expect(within(region).getByText("Juli tách GMV thành 5 luồng.")).toHaveClass("ui-body");
  });

  it("StatusPill: default labels per status", () => {
    render(
      <>
        <StatusPill status="live" />
        <StatusPill status="integrating" />
      </>,
    );
    expect(screen.getByText("Đang hoạt động")).toHaveClass("ui-pill--live");
    expect(screen.getByText("Đang tích hợp")).toHaveClass("ui-pill--integrating");
  });

  it("StepList: the 5-step loop, numbered, with '03 · bạn' on Duyệt", () => {
    render(<StepList />);
    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(LOOP_STEPS.length);
    expect(screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent)).toEqual([
      "Phân tích",
      "Đề xuất",
      "Duyệt",
      "Thực thi",
      "Đo lường",
    ]);
    expect(items[2]).toHaveClass("ui-step--you");
    expect(within(items[2]).getByText("03 · bạn")).toBeInTheDocument();
    expect(within(items[0]).getByText("01")).toBeInTheDocument();
  });

  it("FunnelDiagram: one img with a sentence label, highlight marked", () => {
    const { container } = render(<FunnelDiagram highlight="ctor" />);
    const img = screen.getByRole("img");
    expect(img).toHaveAccessibleName(/GMV bằng Lượt hiển thị nhân CTR nhân CTOR nhân AOV.*Đang nghẽn: CTOR/);
    expect(container.querySelector('[data-step="ctor"]')).toHaveClass("ui-funnel__box--hot");
    expect(within(img).getByText("Đang nghẽn")).toBeInTheDocument();
    expect(img.textContent).toContain("GMV");
  });

  it("FaqList: <details> per item; schema only when asked", () => {
    const items = [
      { question: "Juli đọc dữ liệu nào?", answer: "Dữ liệu shop qua Open API." },
      { question: "Khi nào có Shopee?", answer: "Đang tích hợp." },
    ];
    const { container, rerender } = render(<FaqList items={items} openFirst />);
    const details = container.querySelectorAll("details");
    expect(details).toHaveLength(2);
    expect(details[0]).toHaveAttribute("open");
    expect(container.querySelector('script[type="application/ld+json"]')).toBeNull();
    rerender(<FaqList items={items} schema />);
    const json = container.querySelector('script[type="application/ld+json"]')?.textContent ?? "";
    expect(json).toContain("FAQPage");
    expect(json).toContain("Khi nào có Shopee?");
  });

  it("TocNav: desktop list + mobile disclosure, active item marked", () => {
    const { container } = render(
      <TocNav
        activeId="luong"
        items={[
          { id: "luong", label: "Năm luồng truy cập" },
          { id: "pheu", label: "Phễu của từng luồng" },
        ]}
      />,
    );
    const nav = screen.getByRole("navigation", { name: "Trên trang này" });
    expect(container.querySelector("details.ui-toc__mobile summary")).toHaveTextContent("Trên trang này");
    const links = within(nav).getAllByRole("link", { name: "Năm luồng truy cập" });
    expect(links).toHaveLength(2);
    for (const link of links) {
      expect(link).toHaveAttribute("href", "#luong");
      expect(link).toHaveAttribute("aria-current", "location");
    }
  });

  it("Breadcrumb: ancestors linked, current page marked", () => {
    render(<Breadcrumb current="Phân tích shop" items={[{ href: "/san-pham", label: "Sản phẩm" }]} />);
    const nav = screen.getByRole("navigation", { name: "Breadcrumb" });
    expect(within(nav).getByRole("link", { name: "Sản phẩm" })).toHaveAttribute("href", "/san-pham");
    expect(within(nav).getByText("Phân tích shop")).toHaveAttribute("aria-current", "page");
  });
});

describe("Icon", () => {
  it("has the D44 set, decorative by default, labelled when given a label", () => {
    for (const name of ["shield-check", "check-square", "undo", "mail", "play", "menu", "chevron-down", "arrow-right", "alert", "check"]) {
      expect(ICON_NAMES, name).toContain(name);
    }
    const { container } = render(
      <>
        <Icon name="mail" />
        <Icon label="Cảnh báo" name="alert" strokeWidth={1.5} />
      </>,
    );
    expect(container.querySelector('[data-icon="mail"]')).toHaveAttribute("aria-hidden", "true");
    const alert = screen.getByRole("img", { name: "Cảnh báo" });
    expect(alert).toHaveAttribute("stroke", "currentColor");
    expect(alert).toHaveAttribute("stroke-width", "1.5");
  });
});
