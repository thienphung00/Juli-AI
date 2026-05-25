# KiotViet Products API

## Base URL

```
https://public.kiotapi.com/products
```

## Endpoints

### List Products

```
GET /products
```

Returns all products for the authenticated retailer.

**Query Parameters:**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `orderBy` | string | No | Sort field (e.g., `Name`) |
| `orderDirection` | string | No | `ASC` (default) or `DESC` |
| `lastModifiedFrom` | datetime | No | Filter by last modification time |
| `pageSize` | int | No | Items per page (default: 20, max: 100) |
| `currentItem` | int | No | Offset for pagination (default: 0) |
| `includeInventory` | boolean | No | Include stock information |
| `includePricebook` | boolean | No | Include price book data |
| `IncludeSerials` | boolean | No | Include serial/IMEI data |
| `IncludeBatchExpires` | boolean | No | Include batch/expiry data |
| `includeWarranties` | boolean | No | Include warranty info |
| `categoryId` | int | No | Filter by category ID |
| `BranchIds` | int[] | No | Filter inventory by branch IDs |
| `includeRemoveIds` | boolean | No | Include deleted product IDs |
| `includeQuantity` | boolean | No | Include min/max stock levels |
| `productType` | int | No | 1=combo, 2=standard, 3=service |
| `includeMaterial` | boolean | No | Include component products |
| `isActive` | boolean | No | Filter active/inactive products |
| `name` | string | No | Search by product name |
| `tradeMarkId` | int | No | Filter by brand ID |
| `IncludeProductShelves` | boolean | No | Include shelf locations |

**Response:**

```json
{
  "total": 150,
  "pageSize": 20,
  "removeId": [],
  "data": [
    {
      "id": 12345,
      "code": "SP001",
      "barCode": "8934567890123",
      "name": "Product Name",
      "fullName": "Product Name - Size M - Box",
      "categoryId": 1,
      "categoryName": "Category A",
      "tradeMarkId": 5,
      "tradeMarkName": "Brand X",
      "description": "Product description",
      "allowsSale": true,
      "hasVariants": true,
      "basePrice": 150000.00,
      "weight": 0.5,
      "unit": "piece",
      "masterUnitId": null,
      "masterProductId": null,
      "conversionValue": 1,
      "isActive": true,
      "modifiedDate": "2024-01-15T10:30:00",
      "createdDate": "2024-01-01T08:00:00",
      "attributes": [
        {
          "productId": 12345,
          "attributeName": "Size",
          "attributeValue": "M"
        }
      ],
      "units": [
        {
          "id": 12346,
          "code": "SP001-BOX",
          "name": "Product Name",
          "fullName": "Product Name - Box",
          "unit": "box",
          "conversionValue": 12,
          "basePrice": 1700000.00
        }
      ],
      "images": [{"Image": "https://..."}],
      "inventories": [
        {
          "productId": 12345,
          "productCode": "SP001",
          "productName": "Product Name",
          "branchId": 1,
          "branchName": "Main Store",
          "onHand": 50.0,
          "cost": 100000.00,
          "onOrder": 10.0,
          "reserved": 5.0,
          "minQuality": 10.0,
          "maxQuality": 100.0
        }
      ],
      "priceBooks": [
        {
          "priceBookId": 1,
          "priceBookName": "General",
          "productId": 12345,
          "isActive": true,
          "startDate": null,
          "endDate": null,
          "price": 150000.00
        }
      ]
    }
  ]
}
```

---

### Get Product by ID

```
GET /products/{id}
```

### Get Product by Code

```
GET /products/code/{code}
```

---

### Create Product

```
POST /products
```

**Request Body:**

```json
{
  "name": "New Product",
  "code": "SP002",
  "barCode": "8934567890124",
  "fullName": "New Product - Size L",
  "categoryId": 1,
  "allowsSale": true,
  "description": "Product description",
  "hasVariants": true,
  "isProductSerial": false,
  "attributes": [
    {
      "attributeName": "Size",
      "attributeValue": "L"
    }
  ],
  "unit": "piece",
  "masterProductId": null,
  "masterUnitId": null,
  "conversionValue": 1,
  "inventories": [
    {
      "branchId": 1,
      "branchName": "Main Store",
      "onHand": 100,
      "cost": 80000.00
    }
  ],
  "basePrice": 150000.00,
  "weight": 0.3,
  "images": ["https://example.com/image.jpg"]
}
```

**Notes:**
- If `attributeName` doesn't exist in the system, it will be auto-created.
- `barCode` maximum length: 16 characters.
- `masterUnitId` = NULL for base unit products.

---

### Create Multiple Products (Batch)

```
POST /listaddproducts
```

**Request Body:**

```json
{
  "listProducts": [
    { /* product object */ },
    { /* product object */ }
  ]
}
```

---

### Update Product

```
PUT /products/{id}
```

**Request Body:** Same structure as Create, with `id` in URL path.

---

### Update Multiple Products (Batch)

```
PUT /listupdatedproducts
```

**Request Body:**

```json
{
  "listProducts": [
    {
      "id": 12345,
      "name": "Updated Name"
    }
  ]
}
```

---

### Delete Product

```
DELETE /products/{id}
```

**Response:**
```json
{
  "message": "Xóa dữ liệu thành công"
}
```

---

### Get Product Attributes

```
GET /attributes/allwithdistinctvalue
```

Returns all product attributes with their distinct values.

**Response:**
```json
[
  {
    "name": "Color",
    "id": 1,
    "attributeValues": [
      { "value": "Red", "attributeId": 1 },
      { "value": "Blue", "attributeId": 1 }
    ]
  }
]
```

---

### Get Inventory On Hand

```
GET /productOnHands
```

**Query Parameters:**

| Parameter | Type | Description |
|---|---|---|
| `orderBy` | string | Sort field (e.g., `Code`) |
| `lastModifiedFrom` | datetime | Filter by modification time |
| `branchIds` | int[] | Filter by branch IDs |
| `pageSize` | int | Items per page (max 100) |
| `currentItem` | int | Pagination offset |

**Response:**
```json
{
  "total": 500,
  "pageSize": 20,
  "data": [
    {
      "id": 12345,
      "code": "SP001",
      "createdDate": "2024-01-01",
      "modifiedDate": "2024-01-15",
      "inventories": [
        {
          "branchId": 1,
          "onhand": 50.0,
          "reserved": 5.0
        }
      ]
    }
  ]
}
```

## Product Types

| Value | Meaning |
|---|---|
| 1 | Combo product |
| 2 | Standard product |
| 3 | Service product |

## Tax Configuration

Products support two tax methods:

- **Deduction method** (`taxType: "khau_tru"`): Values: 0%, 5%, 8%, 10%, "KCT", "KKKNT"
- **Direct method** (`taxType: "truc_tiep"`): Values: 1%, 2%, 3%, 5%, or null
