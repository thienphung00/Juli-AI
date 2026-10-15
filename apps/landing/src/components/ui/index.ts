/**
 * Shared landing UI (D44, P34-A). Import from `components/ui`; every component
 * is documented with props and mockup recipes in ./README.md. Styles live in
 * ./ui.css (imported once by app/layout.tsx) on the tokens in
 * src/styles/tokens.css.
 */
export { BirdGlyph, type BirdGlyphProps, BrandMark, type BrandMarkProps } from "./brand";
export {
  Button,
  buttonClassName,
  type ButtonProps,
  type ButtonSize,
  type ButtonVariant,
  LinkButton,
  type LinkButtonProps,
  TextLink,
  type TextLinkProps,
} from "./button";
export {
  Breadcrumb,
  type BreadcrumbProps,
  FaqList,
  type FaqListProps,
  FeatureRow,
  type FeatureRowProps,
  FunnelDiagram,
  type FunnelDiagramProps,
  type FunnelStep,
  LOOP_STEPS,
  type MarketStatus,
  StatusPill,
  type StatusPillProps,
  type Step,
  StepList,
  type StepListProps,
  type TocItem,
  TocNav,
  type TocNavProps,
} from "./blocks";
export { Icon, ICON_NAMES, type IconName, type IconProps } from "./icon";
export {
  Card,
  type CardProps,
  CheckList,
  type CheckListProps,
  Container,
  type ContainerProps,
  Eyebrow,
  type EyebrowProps,
  Heading,
  type HeadingProps,
  type HeadingSize,
  Section,
  SectionIntro,
  type SectionIntroProps,
  type SectionProps,
} from "./section";
export { SAMPLE_DATA_CAPTION, Shot, ShotFrame, type ShotFrameProps, type ShotImage, type ShotProps } from "./shot";
export { SiteFooter } from "./site-footer";
export { SiteHeader, type SiteHeaderProps } from "./site-header";
