# Seller Centre recon 2026-11-03 (ORY sub-account, read-only)

## Products — /portal/product/list/all
- GET /api/v3/opt/mpsku/list/v2/get_product_list?page_number&page_size&list_type&need_ads  (total 114 items)
  product: id, name, status, cover_image, parent_sku, create_time, modify_time,
  price_detail{price_min,price_max,selling_price_min,selling_price_max,has_discount,max_discount_percentage,max_discount},
  stock_detail{total_available_stock,total_seller_stock,total_shopee_stock,low_stock_status,advanced_stock{sellable_stock,in_transit_stock}},
  promotion{wholesale,has_bundle_deal}, statistics{view_count,liked_count,sold_count},
  tag{has_discount,has_bundle_deal,has_add_on_deal,has_ams_commission,unlist,...}, boost_info,
  model_list[{id,name,sku,tier_index,is_default,image,statistics{sold_count},price_detail{origin_price,promotion_price},stock_detail}]
- GET get_product_extensive_info?product_ids=… (bidding price hints, buy box, ads_potential…)
- POST /api/v3/opt/product/get_campaign_info_by_item_list/ (active campaigns per item)
- Missing here: rating, category path (category tree endpoint exists; per-item category needs detail page)

## Ads — /portal/marketing/pas/index
- POST /api/pas/v1/homepage/query/ body{start_time,end_time,filter_list,offset,limit,use_paid_gmv}
  entry: title, image, type/subtype, state, campaign{campaign_id,daily_budget,total_budget,start_time,end_time,roi_two_target},
  report{impression,click,ctr,cost,cpc,cpm,broad_gmv,broad_order,broad_roi,broad_cir,direct_gmv,direct_order,direct_roi,direct_cir,
         product_impression,product_click,product_ctr,avg_rank,sov,reach,page_views,unique_visitors,checkout,atc,voucher_amount,voucher_sales},
  ratio{same keys = change vs previous period}
  → one day per call = daily per campaign (replaces the period-only CSV)
- POST /api/pas/v1/report/get_time_graph/ body{agg_interval,campaign_type,start_time,end_time,need_roi_target_setting,filter_params}
  report_by_time[]: metrics + roi_target_setting{value,is_cold_start}, target_broad_roi_setting, boost settings → ROAS target per day
- POST /api/pas/v1/report/export_job/... (export centre for file reports)
- Pages show upsell modals ("Áp dụng cho tất cả") — the connector must never click them; dismiss only via ✕ or not at all.

## Vouchers — /portal/marketing/vouchers/list
- GET /api/marketing/v3/voucher/list/?offset&limit&promotion_type
  voucher_id, name, voucher_code, start_time, end_time, value (VND off) | discount (%), max_value, min_price (min spend),
  usage_limit, current_usage, distributed_count, status/fe_status, use_type, rule{items, reward_type, purpose, choose_users,
  usage_limit_per_user, is_seller_absorbed, display_from…} → voucher settings + live usage (performance stays in voucher_*.xlsx)
- GET /api/marketing/v3/voucher/promotion_tool/metrics/

## Promotions — /portal/marketing/list/discount
- /api/marketing/v3/public/discount/list/ , /discount/active/ , /discount/metrics/ (ORY has no programme running today: data = null;
  map the list shape once one exists). Performance stays in discount_*.xlsx (already loaded).
- Flash Sale: /portal/marketing/shop-flash-sale/list (not opened this pass; Flash Sale exports already loaded).

## Affiliate — /portal/web-seller-affiliate/homepage
- /api/v3/affiliateplatform/gql (GraphQL POST), creator/list, commissions/category_setting, dashboard/latest_report_date
  → use the page's own exports (path D); the loader already parses all six affiliate files.

## Shop performance — /portal/accounthealth
- GET /api/accounthealth/v1/sc/shops/overview {failed_metric_count, penalty_point, performance_rating}
- GET /api/accounthealth/v1/sc/shops/metric_list [{metric_id, display_value, target_value, compare_result, metric_tag}]
- GET /api/accounthealth/v1/sc/metric/configs (metric_id → name; chat response rate lives here)
→ replaces the operator form for chat response % / ratings.

## Orders — /portal/sale/order
- List visible (≈5.660 orders) with "Xuất" and "Lịch sử Xuất Báo cáo"; no list endpoint observed in resource timing.
  → path D: trigger "Xuất", collect the file from the export history, strip PII in the browser. Not clicked during recon.

## Finance
- Sidebar has no Tài chính › Doanh thu for this sub-account → fees (M2) still blocked; the client's manager must grant the finance section.

## Connector plan from this recon
1. product list reader (get_product_list, paged; + campaign_info_by_item_list) → platform_items + platform_item_snapshots + images
2. ads reader (homepage/query per day + get_time_graph) → ads_campaign_daily + ROAS-target history
3. voucher settings reader (voucher/list) → platform_promotions (settings)
4. account health reader (overview + metric_list + configs) → shop performance
5. export trigger for orders + affiliate (path D)
Rules: never click upsell/apply buttons (ads page shows "Áp dụng cho tất cả" modal); read-only GETs or the page's own POST queries;
pace requests; stop on CAPTCHA/login.
