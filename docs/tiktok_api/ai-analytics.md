# AI & Predictive Analytics

## Overview

Machine learning features layered on top of the TikTok Shop data pipeline to provide predictive insights, anomaly detection, and automated recommendations. These features differentiate the platform from basic dashboard tools.

## ML Feature Roadmap

| Feature | Model Type | Input Data | Priority |
|---------|-----------|------------|----------|
| Demand Forecasting | Time-series | Historical orders, seasonality | P1 |
| Stockout Prediction | Classification | Inventory + velocity | P1 |
| Anomaly Detection | Unsupervised | Daily sales, returns | P2 |
| Customer Churn | Classification | Order frequency, recency | P2 |
| Product Trend Scoring | Regression | Early sales signals | P3 |
| Livestream Performance | Regression | Session metrics | P3 |
| Price Optimization | Reinforcement | Sales vs price elasticity | P4 |

---

## 1. Demand Forecasting

### Problem

Predict future sales volume per product/SKU to inform inventory decisions.

### Approach

| Aspect | Detail |
|--------|--------|
| Model | Prophet (baseline), LSTM or N-BEATS (advanced) |
| Granularity | Daily forecast per SKU per shop |
| Horizon | 7-day and 30-day predictions |
| Features | Historical daily sales, day-of-week, month, holidays, promotions, category trends |
| Training | Retrain weekly on rolling 90-day window |
| Output | Point forecast + confidence interval (80%, 95%) |

### Feature Engineering

```python
features = {
    "sales_7d_avg": rolling_mean(sales, 7),
    "sales_30d_avg": rolling_mean(sales, 30),
    "day_of_week": order_date.dayofweek,
    "is_weekend": order_date.dayofweek >= 5,
    "month": order_date.month,
    "is_holiday": check_holiday(order_date, region),
    "days_since_launch": (today - product_launch_date).days,
    "category_trend": category_sales_growth_rate,
    "price_change_flag": price != lag(price, 1),
    "promotion_active": has_active_discount,
}
```

### Integration

- Dashboard shows "Predicted Sales Next 7 Days" per product
- Inventory page shows "Recommended Reorder Quantity" based on forecast + lead time
- Alerts when forecast indicates demand spike (prepare stock)

---

## 2. Inventory Optimization & Stockout Prediction

### Problem

Predict which SKUs will stock out before the seller can reorder, enabling proactive alerts.

### Approach

| Aspect | Detail |
|--------|--------|
| Model | Gradient Boosting (XGBoost/LightGBM) |
| Target | Binary: will stock out within N days? |
| Features | Current stock, daily velocity, velocity trend, lead time, day-of-week patterns |
| Training | Daily retrain on labeled historical stockout events |
| Threshold | Alert when P(stockout) > 0.7 |

### Reorder Point Formula (Baseline)

```python
def calculate_reorder_point(daily_velocity: float, lead_time_days: int, safety_stock_days: int = 3) -> int:
    return int(daily_velocity * (lead_time_days + safety_stock_days))

def recommended_order_quantity(forecast_30d: float, current_stock: int, lead_time_days: int) -> int:
    target_stock = forecast_30d + (daily_velocity * lead_time_days)
    return max(0, int(target_stock - current_stock))
```

---

## 3. Anomaly Detection

### Problem

Automatically detect unusual patterns in sales, returns, or operations that require seller attention.

### Approach

| Aspect | Detail |
|--------|--------|
| Model | Isolation Forest + Statistical (Z-score) |
| Targets | Daily revenue, order count, return rate, avg order value |
| Detection | Flag when metric deviates > 2.5σ from rolling 30-day baseline |
| Latency | Near real-time (process with each batch of new data) |

### Anomaly Types

| Type | Signal | Potential Cause |
|------|--------|-----------------|
| Revenue spike | Daily GMV > 3x average | Viral product, campaign success |
| Revenue drop | Daily GMV < 50% average | Listing suspended, stock issues |
| Return spike | Return rate > 2x average | Quality issue, wrong descriptions |
| Order velocity change | Sudden sustained increase | Trending product |
| AOV anomaly | Average order > 5x normal | Bulk buyer, potential fraud |

### Implementation

```python
from sklearn.ensemble import IsolationForest

def detect_anomalies(daily_metrics: pd.DataFrame, contamination: float = 0.05) -> pd.Series:
    model = IsolationForest(contamination=contamination, random_state=42)
    features = daily_metrics[["revenue", "order_count", "return_rate", "aov"]]
    predictions = model.fit_predict(features)
    return predictions == -1  # True = anomaly
```

---

## 4. Customer Churn Prediction

### Problem

Identify buyers unlikely to return, enabling targeted retention efforts (if seller has means to reach them).

### Approach

| Aspect | Detail |
|--------|--------|
| Model | Logistic Regression (baseline), XGBoost (advanced) |
| Definition | Churn = no purchase within 90 days of last order |
| Features | Recency, frequency, monetary value (RFM), category diversity, return history |
| Training | Monthly retrain on labeled cohort data |
| Output | Churn probability per customer |

### RFM Features

```python
rfm_features = {
    "recency_days": (today - last_order_date).days,
    "frequency_90d": orders_in_last_90_days,
    "monetary_total": total_lifetime_spend,
    "monetary_avg": average_order_value,
    "category_diversity": unique_categories_purchased,
    "return_rate": returns / total_orders,
    "time_between_orders_avg": avg_days_between_purchases,
}
```

### Limitations

TikTok provides buyer_id but limited contact info. Churn insights are useful for:
- Understanding customer health metrics
- Identifying product/service issues driving churn
- Informing TikTok ad retargeting strategies

---

## 5. Product Trend Scoring

### Problem

Identify products with viral potential early, so sellers can increase stock and marketing spend.

### Approach

| Aspect | Detail |
|--------|--------|
| Model | Gradient Boosting Regressor |
| Target | Sales acceleration (next-7-day sales / previous-7-day sales) |
| Features | Early velocity, velocity acceleration, category growth, price point, listing age |
| Training | Weekly on products with >14 days of history |
| Output | Trend score 0-100 (higher = more likely to trend) |

### Early Signals

```python
trend_features = {
    "velocity_3d": sales_last_3_days / 3,
    "velocity_7d": sales_last_7_days / 7,
    "acceleration": velocity_3d / max(velocity_7d, 1),
    "category_growth": category_sales_wow_change,
    "price_vs_category_avg": product_price / category_avg_price,
    "listing_age_days": (today - listing_date).days,
    "review_velocity": new_reviews_last_3_days,
}
```

---

## 6. Livestream Performance Prediction

### Problem

Predict expected revenue from an upcoming livestream based on historical session data.

### Approach

| Aspect | Detail |
|--------|--------|
| Model | Linear Regression (baseline) or Random Forest |
| Target | Session revenue (total sales during live) |
| Features | Duration, time of day, day of week, products featured, host history |
| Data Source | Inferred from order timestamps correlated with known live schedules |

### Limitations

TikTok Shop API does not directly expose livestream analytics. We must:
1. Have sellers input livestream schedules
2. Correlate orders placed during live windows to sessions
3. Use affiliate links as attribution signals

---

## ML Pipeline Architecture

```
┌────────────────┐     ┌────────────────┐     ┌────────────────┐
│  Data Store    │────▶│  Feature Store │────▶│  Model Training│
│  (ClickHouse)  │     │  (Redis/DB)    │     │  (Daily/Weekly)│
└────────────────┘     └────────────────┘     └───────┬────────┘
                                                       │
                                                       ▼
                                              ┌────────────────┐
                                              │  Model Registry│
                                              │  (MLflow/S3)   │
                                              └───────┬────────┘
                                                       │
                              ┌─────────────────────────┼─────────────────────────┐
                              ▼                         ▼                         ▼
                    ┌────────────────┐       ┌────────────────┐       ┌────────────────┐
                    │ Batch Predict  │       │ Real-time Score│       │  Dashboard     │
                    │ (Airflow job)  │       │ (FastAPI svc)  │       │  (shows preds) │
                    └────────────────┘       └────────────────┘       └────────────────┘
```

### Pipeline Components

| Component | Technology | Schedule |
|-----------|-----------|----------|
| Feature computation | Python + SQL (ClickHouse) | Hourly |
| Model training | Python (scikit-learn, XGBoost) | Weekly |
| Batch predictions | Airflow DAG | Daily |
| Real-time scoring | FastAPI microservice | On-demand |
| Model registry | MLflow or S3 versioned | Per training run |
| Monitoring | Evidently AI / custom | Continuous |

### Model Monitoring

Track these to detect model drift:
- Prediction distribution (shift from training)
- Feature distribution (input drift)
- Accuracy on recent labeled data (when available)
- Business metric correlation (do forecasts match actuals?)

## Dataset Requirements

| Dataset | Source | Volume Estimate | Retention |
|---------|--------|-----------------|-----------|
| Order history | Orders API + webhooks | ~1000 orders/seller/month | 2 years |
| Product catalog | Products API | ~100-1000 SKUs/seller | Current + 6mo history |
| Inventory snapshots | Inventory API (daily) | ~1000 records/seller/day | 1 year |
| Settlement data | Finance API | ~1000 records/seller/month | 2 years |
| Customer orders | Derived from orders | ~500 unique buyers/seller/month | 2 years |

## Tech Stack for ML

| Layer | Technology |
|-------|-----------|
| Training | Python 3.11+, scikit-learn, XGBoost, Prophet |
| Deep Learning | PyTorch (if needed for LSTM/transformers) |
| Orchestration | Airflow or Prefect |
| Feature Store | Feast or custom (Redis + PostgreSQL) |
| Model Serving | FastAPI + Docker |
| Monitoring | Evidently AI, Prometheus custom metrics |
| Compute | AWS SageMaker or GCP AI Platform (training), EC2/GKE (serving) |
