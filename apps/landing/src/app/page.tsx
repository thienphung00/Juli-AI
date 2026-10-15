import { HOME_FAQ } from "../components/home/home-content";
import {
  AudienceSection,
  CapabilityRows,
  FaqSection,
  HomeHero,
  LoopSection,
  MarketplaceStrip,
  PricingBand,
  SafetySection,
  TransparencySection,
} from "../components/home/home-sections";
import { SiteFooter } from "../components/ui/site-footer";
import { SiteHeader } from "../components/ui/site-header";
import { HERO_VIDEO_SCHEMA } from "../lib/media";
import { buildMetadata, faqPageSchema, JsonLd, videoObjectSchema } from "../lib/seo";

export const metadata = buildMetadata("/");

/**
 * Homepage = company + product overview (D43.2), laid out to the approved
 * mockups (D44: fasttrack/design/p34/Main.dc.html + HomeMobile.dc.html).
 * Detailed selling lives on `/san-pham` and the capability pages it links to.
 * FAQPage JSON-LD comes from here only (FaqList renders without `schema`).
 */
export default function LandingPage() {
  return (
    <>
      <JsonLd data={[videoObjectSchema(HERO_VIDEO_SCHEMA), faqPageSchema(HOME_FAQ)]} />
      <SiteHeader />
      <main>
        <HomeHero />
        <MarketplaceStrip />
        <LoopSection />
        <CapabilityRows />
        <SafetySection />
        <AudienceSection />
        <TransparencySection />
        <PricingBand />
        <FaqSection />
      </main>
      <SiteFooter />
    </>
  );
}
