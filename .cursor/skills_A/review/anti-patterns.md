# Anti-Patterns & Fixes

Common violations detected during engineering standards review.

## Reliability

### Silent Exception Swallowing

```python
# BAD
try:
    result = await process(data)
except Exception:
    pass

# GOOD
try:
    result = await process(data)
except ValidationError as e:
    logger.warning("validation_failed", extra={"input": data, "error": str(e)})
    raise
except Exception as e:
    logger.error("process_unexpected_failure", exc_info=True)
    raise ProcessingError("Failed to process data") from e
```

### Unprotected External Calls

```python
# BAD — no timeout, no retry, no fallback
result = await litellm.completion(model="gemini-flash", messages=msgs)

# GOOD
try:
    result = await litellm.completion(
        model="gemini-flash",
        messages=msgs,
        timeout=30,
        num_retries=3,
    )
except Exception as e:
    logger.error("ai_call_failed", extra={"model": "gemini-flash", "error": str(e)})
    result = fallback_computation(data)
```

### Missing Idempotency

```python
# BAD — duplicate webhook creates duplicate order
@app.post("/webhooks/grabfood")
async def handle_order(payload: dict):
    order = create_order(payload)
    return {"id": order.id}

# GOOD
@app.post("/webhooks/grabfood")
async def handle_order(payload: dict):
    idempotency_key = payload["order_id"]
    existing = await get_order_by_external_id(idempotency_key)
    if existing:
        return {"id": existing.id}
    order = await create_order(payload)
    return {"id": order.id}
```

## Security

### SQL Injection via String Formatting

```python
# BAD
query = f"SELECT * FROM orders WHERE customer_id = '{customer_id}'"

# GOOD
query = select(Order).where(Order.customer_id == customer_id)
```

### Secrets in Source

```python
# BAD
API_KEY = "sk-1234567890abcdef"

# GOOD
API_KEY = os.environ["KIOTVIET_API_KEY"]
```

## Observability

### Unstructured Logging

```python
# BAD
print(f"Order {order_id} failed for {email}")

# GOOD
logger.error("order_failed", extra={
    "order_id": order_id,
    "customer_email": mask_email(email),
    "reason": "payment_declined",
})
```

## Performance

### N+1 Query Pattern

```python
# BAD
orders = await get_orders(shop_id)
for order in orders:
    items = await get_order_items(order.id)  # N queries

# GOOD
orders = await get_orders_with_items(shop_id)  # 1 query with JOIN/prefetch
```

### Unbounded Query Results

```python
# BAD
all_customers = await db.execute(select(Customer))

# GOOD
customers = await db.execute(
    select(Customer).limit(100).offset(page * 100)
)
```
