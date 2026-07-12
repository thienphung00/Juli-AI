"""Threshold constants ported from apps/dashboard/src/lib/operations/thresholds.ts."""

SHOP_AGE_MID_LARGE_MIN_DAYS = 90
GMV_METRICS_MIN_COUNT = 2

# TikTok VN dispatch SLA proxy for Orders at SLA Risk (T5 deadline rule).
# Source: docs/integrations/tiktok_platform/seller/operational-limits.md
# FDR/LDR cutoff — orders before 18:00 ship same working day; after 18:00 by
# 11:59 next working day. Phase 2 uses a conservative 48h window until Partner
# API exposes per-order SLA deadlines.
ORDER_DISPATCH_SLA_HOURS = 48
