# Core Dashboard Features

## Overview

The analytics dashboard transforms raw TikTok Shop data into actionable business insights. Features are prioritized by seller impact and data availability from the API.

## Feature Matrix

| Feature | Data Source | Complexity | MVP? |
|---------|------------|------------|------|
| Revenue & GMV | Orders + Settlements | Low | Yes |
| Order Analytics | Orders | Low | Yes |
| Product Performance | Orders + Products | Medium | Yes |
| Inventory Alerts | Inventory + Orders | Medium | Yes |
| Fulfillment Health | Orders (shipping) | Medium | Yes |
| Customer Retention | Orders (buyer_id) | High | No |
| Affiliate ROI | Affiliate endpoints | Medium | No |
| Profit Analytics | Settlements + COGS | High | No |
| Livestream Conversion | Orders + timestamps | High | No |
| Trend Detection | Orders (time-series) | High | No |

---

## 1. Revenue & GMV Analytics

### Metrics

| Metric | Calculation | Granularity |
|--------|-------------|-------------|
| Gross Merchandise Value (GMV) | SUM(order.total_amount) for completed orders | Daily/Weekly/Monthly |
| Net Revenue | GMV - platform fees - affiliate commissions - returns | Daily/Weekly/Monthly |
| Average Order Value (AOV) | GMV / order_count | Daily |
| Revenue Growth | (current_period - previous_period) / previous_period × 100 | WoW, MoM |

### Visualizations

- Line chart: Daily GMV with 7-day moving average
- Bar chart: Revenue by product category
- KPI cards: Today's GMV, MTD revenue, YoY growth
- Breakdown table: Revenue vs platform fees vs net (from settlement data)

### Fee Breakdown (from Settlement API)

```
Gross Revenue
  - Platform Commission (varies 2-8%)
  - Affiliate Commission (if applicable)
  - Transaction Fee
  - Shipping Subsidy (region-dependent)
  = Net Settlement Amount
```

---

## 2. Order Analytics

### Metrics

| Metric | Calculation |
|--------|-------------|
| Total Orders | COUNT(orders) by period |
| Orders by Status | GROUP BY status |
| Cancellation Rate | cancelled_orders / total_orders × 100 |
| Return Rate | returned_orders / delivered_orders × 100 |

### Visualizations

- Real-time order feed (WebSocket-driven)
- Status funnel: Pending → Paid → Shipped → Delivered → Completed
- Hourly order heatmap (identify peak selling times)
- Geographic distribution (by shipping address country/region)

---

## 3. Product Performance

### Metrics

| Metric | Calculation |
|--------|-------------|
| Units Sold | SUM(line_item.quantity) per product |
| Product Revenue | SUM(line_item.sale_price × quantity) per product |
| Conversion Rate | Orders containing product / product page views (if available) |
| Return Rate | Returns for product / units sold |
| Revenue per SKU | Revenue grouped by SKU variant |

### Visualizations

- Top 10 products by revenue (bar chart)
- Product trend lines (7-day moving average of daily sales)
- Viral product alerts (>200% increase vs prior period)
- Category breakdown (treemap or pie chart)
- SKU variant comparison (which color/size sells best)

---

## 4. Inventory Alerts & Forecasting

### Metrics

| Metric | Calculation |
|--------|-------------|
| Current Stock | From inventory API per SKU |
| Daily Velocity | AVG(units_sold) over last 7 days |
| Days of Stock | current_stock / daily_velocity |
| Stockout Risk | Products with days_of_stock < threshold |
| Overstock | Products with days_of_stock > 90 |

### Alert Rules

| Condition | Severity | Action |
|-----------|----------|--------|
| days_of_stock < 3 | Critical | Immediate notification |
| days_of_stock < 7 | Warning | Daily digest |
| stock = 0 | Critical | Auto-pause listing (optional) |
| velocity spike > 3x normal | Info | Demand surge alert |

### Visualizations

- Inventory health scorecard (red/yellow/green per SKU)
- Stock vs velocity chart (identify reorder needs)
- Forecast line: projected stock depletion date
- Reorder recommendation table (quantity based on lead time + safety stock)

---

## 5. Fulfillment & SLA Health

### TikTok SLA Thresholds

| Metric | Target | Penalty Threshold |
|--------|--------|-------------------|
| Late Dispatch Rate | < 4% | > 4% triggers warnings |
| On-time Shipping | > 85% | < 85% risks account penalty |
| Valid Tracking Rate | > 95% | Low rate impacts visibility |
| Cancellation Rate | < 2% | High rate risks suspension |

### Metrics

| Metric | Calculation |
|--------|-------------|
| Ship-on-time Rate | Orders shipped within SLA / total orders × 100 |
| Avg Processing Time | AVG(ship_time - order_time) |
| Late Dispatch Rate | Orders shipped after deadline / total orders × 100 |
| Delivery Success Rate | Delivered / shipped × 100 |

### Visualizations

- SLA compliance gauge (current rate vs target)
- Processing time distribution histogram
- Daily late dispatch trend (with threshold line)
- Fulfillment funnel: Paid → Processing → Shipped → Delivered

---

## 6. Customer Retention (Phase 2)

### Metrics

| Metric | Calculation |
|--------|-------------|
| Repeat Purchase Rate | Buyers with 2+ orders / total unique buyers × 100 |
| Customer Lifetime Value | AVG(total_spend) per customer over lifetime |
| Cohort Retention | % of month-N cohort buying in month N+1, N+2, etc. |
| Churn Rate | Customers not returning within 90 days / total active |

### Visualizations

- Cohort retention heatmap (month-over-month)
- Customer segment pie (new vs returning vs loyal)
- CLTV distribution histogram
- Repurchase interval analysis

### Data Note

TikTok provides `buyer_id` in orders but limited buyer profile data. Retention is computed from order frequency per buyer_id.

---

## 7. Affiliate & Creator ROI (Phase 2)

### Metrics

| Metric | Calculation |
|--------|-------------|
| Affiliate Revenue | Orders attributed to affiliate links |
| Commission Paid | Total affiliate commissions from settlement |
| ROI per Creator | (Attributed revenue - commission) / commission × 100 |
| Conversion by Creator | Orders / clicks per creator link |

### Visualizations

- Creator leaderboard (ranked by attributed revenue)
- Commission vs revenue scatter plot
- Campaign performance over time
- Top-performing content/links

---

## 8. Profit Analytics (Phase 2)

### Calculation

```
Gross Profit = Revenue
             - COGS (user-inputted per product)
             - Platform Commission
             - Affiliate Commission
             - Shipping Cost
             - Returns/Refunds
             - Tax (where applicable)
```

### Data Sources

- Platform fees: Settlement API
- COGS: User-maintained (manual input or ERP sync)
- Shipping: Settlement breakdown or user input
- Returns: Return/refund API data

### Visualizations

- P&L waterfall chart (revenue → expenses → profit)
- Margin by product (identify loss-makers)
- Daily/monthly profit trend
- Fee breakdown by type (pie chart)

---

## 9. Operational Alerts

### Real-Time Alert Types

| Alert | Trigger | Channel |
|-------|---------|---------|
| Large Order | order.total_amount > threshold | Push + Email |
| Stockout | inventory = 0 for active product | Push + SMS |
| SLA Breach Risk | processing_time approaching deadline | Push |
| Revenue Anomaly | Daily revenue < 50% of 7-day avg | Email |
| Auth Expiring | 30 days before token expiry | Email |
| High Return Rate | Return rate > 10% for a product | Email |
| Deauthorization | Seller revokes access | Internal alert |

### Alert Configuration

Sellers should be able to configure:
- Threshold values for each alert type
- Notification channels (email, SMS, in-app, webhook)
- Quiet hours (no notifications between X-Y time)
- Alert frequency (immediate, hourly digest, daily digest)
