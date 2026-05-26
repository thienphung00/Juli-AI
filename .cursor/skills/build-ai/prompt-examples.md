# Prompt Template Examples

## Inventory Forecasting (Tier 1)

```python
{
    "key": "inventory_forecast",
    "version": "1.0.0",
    "system": (
        "You are an inventory forecasting system for Vietnamese retail/F&B businesses. "
        "Analyze historical sales data and produce daily demand predictions. "
        "Output ONLY valid JSON matching the specified schema. "
        "If data is insufficient, set confidence below 0.5 and explain in the notes field."
    ),
    "user_template": (
        "Product: {product_name} (SKU: {sku})\n"
        "Historical daily sales (last {history_days} days): {sales_data}\n"
        "Current stock: {current_stock}\n"
        "Forecast horizon: {horizon} days\n\n"
        "Produce a forecast with daily predicted demand, confidence score, "
        "and reorder recommendation."
    ),
    "output_schema": "ForecastOutput",
    "model": "gemini-flash",
    "temperature": 0.1,
    "max_tokens": 1024,
}
```

## Order Classification (Tier 1)

```python
{
    "key": "order_classification",
    "version": "1.0.0",
    "system": (
        "Classify incoming orders by urgency and type. "
        "Output JSON with fields: category, priority, flags."
    ),
    "user_template": (
        "Order details:\n"
        "- Source: {source}\n"
        "- Items: {items}\n"
        "- Total: {total}\n"
        "- Customer type: {customer_type}\n"
        "- Time: {timestamp}\n\n"
        "Classify this order."
    ),
    "output_schema": "OrderClassification",
    "model": "gemini-flash",
    "temperature": 0.0,
    "max_tokens": 256,
}
```

## Anomaly Explanation (Tier 2)

```python
{
    "key": "anomaly_explanation",
    "version": "1.0.0",
    "system": (
        "You are a business analyst for Vietnamese retail. "
        "Given a detected anomaly in sales/inventory data, explain the likely cause "
        "and recommend actions. Be specific and reference the data provided. "
        "Output structured JSON."
    ),
    "user_template": (
        "Anomaly detected:\n"
        "- Metric: {metric_name}\n"
        "- Expected: {expected_value}\n"
        "- Actual: {actual_value}\n"
        "- Deviation: {deviation_pct}%\n"
        "- Context: {surrounding_data}\n\n"
        "Explain this anomaly and recommend actions."
    ),
    "output_schema": "AnomalyExplanation",
    "model": "claude-sonnet",
    "temperature": 0.3,
    "max_tokens": 2048,
}
```

## Customer Segment Description (Tier 1)

```python
{
    "key": "segment_description",
    "version": "1.0.0",
    "system": (
        "Generate a human-readable description of a customer segment based on its "
        "statistical properties. Use business-friendly language suitable for "
        "Vietnamese F&B/retail owners. Output JSON with name and description fields."
    ),
    "user_template": (
        "Segment statistics:\n"
        "- Avg order frequency: {avg_frequency}/month\n"
        "- Avg order value: {avg_value} VND\n"
        "- Recency: {avg_recency} days since last order\n"
        "- Size: {segment_size} customers ({segment_pct}% of total)\n\n"
        "Generate a name and description for this segment."
    ),
    "output_schema": "SegmentDescription",
    "model": "gemini-flash",
    "temperature": 0.4,
    "max_tokens": 512,
}
```
