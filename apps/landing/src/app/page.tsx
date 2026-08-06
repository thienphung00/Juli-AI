import { ComparisonSection } from "../components/comparison-section";
import { CuriositySection } from "../components/curiosity-section";
import { FeaturesSection } from "../components/features-section";
import { HeroSection } from "../components/hero-section";
import { LandingHeader } from "../components/landing-header";
import { SiteFooter } from "../components/site-footer";
import { StepsSection } from "../components/steps-section";

export default function LandingPage() {
  return (
    <>
      <LandingHeader />
      <main className="lp-main">
        <HeroSection />
        <StepsSection />
        <ComparisonSection />
        <FeaturesSection />
        <CuriositySection />
      </main>
      <SiteFooter />
    </>
  );
}
