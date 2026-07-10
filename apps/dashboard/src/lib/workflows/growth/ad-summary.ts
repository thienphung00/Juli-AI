import type { SellerPersona } from "@/lib/mock-data/seller-personas/schemas";

export interface AdPerformanceSummary {
  totalSpendVnd: number;
  avgRoas: number;
  avgCpcVnd: number;
  totalConversions: number;
  activeCampaignCount: number;
}

export function computeAdSummary(persona: SellerPersona): AdPerformanceSummary {
  const campaigns = persona.ad_campaigns;
  const totalSpendWeight = campaigns.reduce((sum, campaign) => sum + campaign.spend_vnd, 0);
  const activeCampaignCount = campaigns.filter((c) => c.status === "active").length;
  const totalConversions = campaigns.reduce((sum, campaign) => sum + campaign.conversions, 0);

  const avgRoas =
    totalSpendWeight > 0
      ? campaigns.reduce((sum, campaign) => sum + campaign.roas * campaign.spend_vnd, 0) /
        totalSpendWeight
      : 0;

  const avgCpcVnd =
    totalSpendWeight > 0
      ? campaigns.reduce((sum, campaign) => sum + campaign.cpc_vnd * campaign.spend_vnd, 0) /
        totalSpendWeight
      : 0;

  return {
    totalSpendVnd: persona.profile.ad_spend_30d_vnd,
    avgRoas: Math.round(avgRoas * 10) / 10,
    avgCpcVnd: Math.round(avgCpcVnd),
    totalConversions,
    activeCampaignCount,
  };
}
