import { HOME_FAQ } from "../components/home/home-content";
import {
  AudienceSection,
  CapabilitiesSection,
  FinalCta,
  HomeHero,
  HowItWorksSection,
  MarketplaceStrip,
  PricingFaqSection,
  ProblemSection,
  SafetySection,
  TransparencySection,
} from "../components/home/home-sections";
import { LandingHeader } from "../components/landing-header";
import { SiteFooter } from "../components/site-footer";
import { HERO_VIDEO_SCHEMA } from "../lib/media";
import { buildMetadata, faqPageSchema, JsonLd, videoObjectSchema } from "../lib/seo";

export const metadata = buildMetadata("/");

/**
 * Homepage = company + product overview (D43.2, AC-33.5). Detailed selling
 * lives on `/san-pham` and the capability pages it links to.
 */
export default function LandingPage() {
  return (
    <>
      <JsonLd data={[videoObjectSchema(HERO_VIDEO_SCHEMA), faqPageSchema(HOME_FAQ)]} />
      <LandingHeader />
      <main className="lp-main lp-home">
        <HomeHero />
        <MarketplaceStrip />
        <ProblemSection />
        <HowItWorksSection />
        <CapabilitiesSection />
        <SafetySection />
        <AudienceSection />
        <TransparencySection />
        <PricingFaqSection />
        <FinalCta />
      </main>
      <SiteFooter />
    </>
  );
}
