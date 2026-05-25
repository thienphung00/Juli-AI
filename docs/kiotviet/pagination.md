# KiotViet API Pagination

## Overview

KiotViet API uses **offset-based pagination** via `currentItem` and `pageSize` parameters. All list endpoints support pagination.

## Parameters

| Parameter | Type | Default | Max | Description |
|---|---|---|---|---|
| `pageSize` | int | 20 | 100 | Number of items per page |
| `currentItem` | int | 0 | - | Starting offset (0-based) |

## How It Works

- `currentItem` specifies the starting record index.
- `pageSize` specifies how many records to return from that offset.
- The response includes `total` indicating the total number of records available.

### Example: Fetching All Products

**Page 1:**
```
GET /products?pageSize=100&currentItem=0
```

**Page 2:**
```
GET /products?pageSize=100&currentItem=100
```

**Page 3:**
```
GET /products?pageSize=100&currentItem=200
```

Continue until `currentItem >= total`.

## Response Structure

All paginated responses follow this pattern:

```json
{
  "total": 350,
  "pageSize": 100,
  "data": [ /* array of items */ ],
  "timestamp": "2024-01-15T10:30:00"
}
```

| Field | Description |
|---|---|
| `total` | Total number of records matching the query |
| `pageSize` | Actual page size used |
| `data` | Array of records for the current page |
| `timestamp` | Server timestamp of the response |

## Sorting

Paginated results can be sorted using:

| Parameter | Values | Description |
|---|---|---|
| `orderBy` | field name | Field to sort by (e.g., `name`, `createdDate`) |
| `orderDirection` | `ASC`, `DESC` | Sort direction (default: `ASC`) |

## Incremental Sync Pattern

Use `lastModifiedFrom` to fetch only records changed since your last sync:

```
GET /products?lastModifiedFrom=2024-01-15T00:00:00&pageSize=100&currentItem=0
```

This is more efficient than full pagination for regular sync operations.

## Deleted Records

Some endpoints support `includeRemoveIds` or return `removedIds`:

```json
{
  "total": 350,
  "pageSize": 100,
  "data": [...],
  "removedIds": [101, 205, 318]
}
```

Use `removedIds` to detect deletions since `lastModifiedFrom`.

## Implementation Pattern

```python
def fetch_all(endpoint: str, params: dict = None) -> list:
    """Fetch all records from a paginated endpoint."""
    all_data = []
    page_size = 100
    current_item = 0

    while True:
        query = {
            "pageSize": page_size,
            "currentItem": current_item,
            **(params or {})
        }
        response = api_client.get(endpoint, params=query)
        all_data.extend(response["data"])

        current_item += page_size
        if current_item >= response["total"]:
            break

    return all_data
```

## Rate Limit Consideration

Each page request counts against the 5,000 GET requests/hour limit. For a dataset of 10,000 records at `pageSize=100`:
- **100 requests** for a full sync
- Use incremental sync (`lastModifiedFrom`) to minimize requests
