-- P100 owner checks — Supabase SQL editor version (read-only SELECT, one result row).
-- 1) Replace the uuid below with ORY's shops.id   2) Run   3) Copy the single JSON cell back.
WITH params AS (SELECT '00000000-0000-0000-0000-000000000000'::uuid AS shop_id)
SELECT jsonb_build_object(
  '1a days where one product > the shop (orders or gmv), per order', (SELECT coalesce(jsonb_agg(t), '[]'::jsonb) FROM (
SELECT p.order_type,
       p.day,
       p.item_id,
       p.orders  AS product_orders, s.orders AS shop_orders,
       p.gmv     AS product_gmv,    s.gmv    AS shop_gmv,
       p.source, p.scaled_to_totals
FROM shopee_product_metrics_daily p
LEFT JOIN shopee_shop_metrics_daily s
       ON s.shop_id = p.shop_id AND s.day = p.day AND s.order_type = p.order_type
WHERE p.shop_id = (SELECT shop_id FROM params)
  AND p.day >= current_date - 90
  AND (s.id IS NULL OR p.orders > coalesce(s.orders, 0) OR p.gmv > coalesce(s.gmv, 0))
ORDER BY p.order_type, p.day, p.item_id
) t),
  '1b same, counted before / after 2026-10-12', (SELECT coalesce(jsonb_agg(t), '[]'::jsonb) FROM (
SELECT p.order_type,
       (p.day < DATE '2026-10-12') AS before_12_10,
       count(*) AS product_days_over_shop,
       count(DISTINCT p.day) AS days
FROM shopee_product_metrics_daily p
LEFT JOIN shopee_shop_metrics_daily s
       ON s.shop_id = p.shop_id AND s.day = p.day AND s.order_type = p.order_type
WHERE p.shop_id = (SELECT shop_id FROM params)
  AND p.day >= current_date - 90
  AND (s.id IS NULL OR p.orders > coalesce(s.orders, 0) OR p.gmv > coalesce(s.gmv, 0))
GROUP BY 1, 2
ORDER BY 1, 2
) t),
  '1c product sum vs shop per day (confirmed), last 90 days', (SELECT coalesce(jsonb_agg(t), '[]'::jsonb) FROM (
SELECT s.day, s.orders AS shop_orders, sum(p.orders) AS sum_product_orders,
       s.gmv AS shop_gmv, sum(p.gmv) AS sum_product_gmv, s.complete
FROM shopee_shop_metrics_daily s
LEFT JOIN shopee_product_metrics_daily p
       ON p.shop_id = s.shop_id AND p.day = s.day AND p.order_type = s.order_type
WHERE s.shop_id = (SELECT shop_id FROM params) AND s.order_type = 'confirmed'
  AND s.day >= current_date - 90
GROUP BY s.day, s.orders, s.gmv, s.complete
ORDER BY s.day
) t),
  '2a raw platform_daily_metrics coverage per dataset (shop-level ', (SELECT coalesce(jsonb_agg(t), '[]'::jsonb) FROM (
WITH days AS (
  SELECT generate_series(current_date - 90, current_date - 1, interval '1 day')::date AS day
), ds AS (
  SELECT DISTINCT dataset FROM platform_daily_metrics
  WHERE shop_id = (SELECT shop_id FROM params) AND day >= current_date - 90
)
SELECT ds.dataset,
       count(*) FILTER (WHERE r.n IS NULL)  AS days_no_row,
       count(*) FILTER (WHERE r.n IS NOT NULL AND r.all_zero) AS days_all_zero,
       count(*) FILTER (WHERE r.n IS NOT NULL AND NOT r.all_zero) AS days_with_values,
       string_agg(to_char(d.day, 'DD/MM'), ' ' ORDER BY d.day) FILTER (WHERE r.n IS NULL) AS missing_days
FROM ds CROSS JOIN days d
LEFT JOIN LATERAL (
  SELECT count(*) AS n,
         bool_and(coalesce(orders, 0) = 0 AND coalesce(gmv, 0) = 0
                  AND coalesce(impressions, 0) = 0 AND coalesce(clicks, 0) = 0) AS all_zero
  FROM platform_daily_metrics m
  WHERE m.shop_id = (SELECT shop_id FROM params) AND m.dataset = ds.dataset AND m.day = d.day
) r ON r.n > 0
GROUP BY ds.dataset
ORDER BY ds.dataset
) t),
  '2b materialized shop days: no row / NULL / zero, per column (co', (SELECT coalesce(jsonb_agg(t), '[]'::jsonb) FROM (
WITH days AS (
  SELECT generate_series(current_date - 90, current_date - 1, interval '1 day')::date AS day
)
SELECT d.day,
       CASE WHEN s.id IS NULL THEN 'no row'
            WHEN s.orders IS NULL THEN 'NULL'
            WHEN s.orders = 0 THEN 'ZERO'
            ELSE s.orders::text END AS orders,
       CASE WHEN s.id IS NULL THEN '' WHEN s.views IS NULL THEN 'NULL' ELSE s.views::text END AS views,
       CASE WHEN s.id IS NULL THEN '' WHEN s.ads_spend IS NULL THEN 'NULL' ELSE s.ads_spend::text END AS ads_spend,
       CASE WHEN s.id IS NULL THEN '' WHEN s.profit IS NULL THEN 'NULL' ELSE s.profit::text END AS profit,
       s.cogs_coverage, s.complete,
       s.sources
FROM days d
LEFT JOIN shopee_shop_metrics_daily s
       ON s.shop_id = (SELECT shop_id FROM params) AND s.day = d.day AND s.order_type = 'confirmed'
ORDER BY d.day
) t),
  '3a materialized shop daily (what the app shows)', (SELECT coalesce(jsonb_agg(t), '[]'::jsonb) FROM (
SELECT order_type, count(*) AS days,
       sum(ads_spend) AS ads_spend, sum(ads_gmv) AS ads_gmv,
       round(sum(ads_gmv) / nullif(sum(ads_spend), 0), 2) AS roas
FROM shopee_shop_metrics_daily
WHERE shop_id = (SELECT shop_id FROM params) AND day >= current_date - 30
GROUP BY order_type ORDER BY order_type
) t),
  '3b Connector ads_campaign_daily (extra.cost), per segment kind ', (SELECT coalesce(jsonb_agg(t), '[]'::jsonb) FROM (
SELECT (segment = 'all') AS shop_total_row, order_type,
       count(DISTINCT day) AS days, count(DISTINCT platform_source) AS campaigns,
       sum((extra->>'cost')::numeric) AS spend_cost,
       sum(gmv) AS gmv, sum(orders) AS orders,
       round(sum(gmv) / nullif(sum((extra->>'cost')::numeric), 0), 2) AS roas,
       min(day) AS first_day, max(day) AS last_day,
       max(source_version) AS source_version
FROM platform_daily_metrics
WHERE shop_id = (SELECT shop_id FROM params) AND dataset = 'ads_campaign_daily'
  AND day >= current_date - 30
GROUP BY 1, 2 ORDER BY 1, 2
) t),
  '3c Connector ads_campaign_daily, per day (to compare one day wi', (SELECT coalesce(jsonb_agg(t), '[]'::jsonb) FROM (
SELECT day, sum((extra->>'cost')::numeric) AS spend_cost, sum(gmv) AS gmv,
       count(*) AS rows, max(captured_at) AS captured_at
FROM platform_daily_metrics
WHERE shop_id = (SELECT shop_id FROM params) AND dataset = 'ads_campaign_daily' AND segment <> 'all'
  AND day >= current_date - 30
GROUP BY day ORDER BY day
) t),
  '3d CSV ads_campaign_period windows overlapping the last 30 days', (SELECT coalesce(jsonb_agg(t), '[]'::jsonb) FROM (
SELECT period_start, period_end, order_type,
       count(*) FILTER (WHERE coalesce(item_id, '') = '') AS campaign_rows,
       count(*) FILTER (WHERE coalesce(item_id, '') <> '') AS product_rows,
       sum((extra->>'ads_expense')::numeric) FILTER (WHERE coalesce(item_id, '') = '') AS spend_campaign_rows,
       sum((extra->>'ads_expense')::numeric) FILTER (WHERE coalesce(item_id, '') <> '') AS spend_product_rows,
       sum(gmv) FILTER (WHERE coalesce(item_id, '') = '') AS gmv_campaign_rows
FROM platform_period_metrics
WHERE shop_id = (SELECT shop_id FROM params) AND dataset = 'ads_campaign_period'
  AND period_end >= current_date - 30
GROUP BY 1, 2, 3 ORDER BY 1, 2, 3
) t),
  '3e per-source and per-product materialized ads, last 30 days', (SELECT coalesce(jsonb_agg(t), '[]'::jsonb) FROM (
SELECT 'source:' || source AS row_kind, sum(ads_spend) AS ads_spend, sum(ads_gmv) AS ads_gmv,
       sum(ads_orders) AS ads_orders
FROM shopee_source_metrics_daily
WHERE shop_id = (SELECT shop_id FROM params) AND day >= current_date - 30
GROUP BY source
UNION ALL
SELECT 'product (' || order_type || ')', sum(ads_spend), NULL, count(*) FILTER (WHERE ads_spend > 0)
FROM shopee_product_metrics_daily
WHERE shop_id = (SELECT shop_id FROM params) AND day >= current_date - 30
GROUP BY order_type
ORDER BY 1
) t),
  '3f money_scale / drift flags on any dataset', (SELECT coalesce(jsonb_agg(t), '[]'::jsonb) FROM (
SELECT dataset, drift_state, drift_source_version, drift_at, drift_detail
FROM ingest_dataset_status
WHERE shop_id = (SELECT shop_id FROM params)
  AND (drift_state IS DISTINCT FROM 'ok' OR drift_detail::text ILIKE '%money_scale%')
ORDER BY dataset
) t),
  '4 ingest_dataset_status', (SELECT coalesce(jsonb_agg(t), '[]'::jsonb) FROM (
SELECT dataset, platform, last_ingest_at, last_captured_at,
       last_period_start, last_period_end, last_row_count,
       last_source, last_source_version, drift_state, updated_at
FROM ingest_dataset_status
WHERE shop_id = (SELECT shop_id FROM params)
ORDER BY dataset
) t)
) AS p100_checks;
