# KiotViet API Examples

## Authentication

### Get Access Token

```bash
curl -X POST https://id.kiotviet.vn/connect/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "scopes=PublicApi.Access&grant_type=client_credentials&client_id=YOUR_CLIENT_ID&client_secret=YOUR_CLIENT_SECRET"
```

**Response:**
```json
{
  "access_token": "eyJhbGciOiJSU0EtT0FFUCIs...",
  "expires_in": 86400,
  "token_type": "Bearer"
}
```

---

## Products

### List Products with Inventory

```bash
curl -X GET "https://public.kiotapi.com/products?pageSize=50&includeInventory=true&isActive=true" \
  -H "Retailer: your-store-name" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

### Get Product by Code

```bash
curl -X GET "https://public.kiotapi.com/products/code/SP001" \
  -H "Retailer: your-store-name" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

### Create a Product

```bash
curl -X POST https://public.kiotapi.com/products \
  -H "Retailer: your-store-name" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Wireless Keyboard",
    "code": "KB-WIRELESS-001",
    "barCode": "8934567890199",
    "categoryId": 5,
    "allowsSale": true,
    "description": "Bluetooth wireless keyboard",
    "hasVariants": false,
    "unit": "piece",
    "basePrice": 450000,
    "weight": 0.8,
    "inventories": [
      {
        "branchId": 1,
        "onHand": 50,
        "cost": 300000
      }
    ]
  }'
```

### Incremental Product Sync

```bash
curl -X GET "https://public.kiotapi.com/products?lastModifiedFrom=2024-01-15T00:00:00&pageSize=100&includeRemoveIds=true" \
  -H "Retailer: your-store-name" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

---

## Orders

### List Recent Orders

```bash
curl -X GET "https://public.kiotapi.com/orders?pageSize=20&includePayment=true&includeOrderDelivery=true&orderDirection=DESC" \
  -H "Retailer: your-store-name" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

### Create an Order

```bash
curl -X POST https://public.kiotapi.com/orders \
  -H "Retailer: your-store-name" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "branchId": 1,
    "soldById": 5,
    "discount": 0,
    "description": "Online order",
    "method": "Transfer",
    "totalPayment": 0,
    "saleChannelId": null,
    "orderDetails": [
      {
        "productId": 12345,
        "productCode": "KB-WIRELESS-001",
        "productName": "Wireless Keyboard",
        "quantity": 2,
        "price": 450000,
        "discount": 0
      }
    ],
    "orderDelivery": {
      "receiver": "John Doe",
      "contactNumber": "0901234567",
      "address": "123 Main St, District 1",
      "locationName": "Ho Chi Minh City",
      "weight": 1.6
    },
    "customer": {
      "name": "John Doe",
      "contactNumber": "0901234567",
      "address": "123 Main St, District 1",
      "email": "john@example.com"
    }
  }'
```

---

## Customers

### Search Customer by Phone

```bash
curl -X GET "https://public.kiotapi.com/customers?contactNumber=0901234567" \
  -H "Retailer: your-store-name" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

### Create a Customer

```bash
curl -X POST https://public.kiotapi.com/customers \
  -H "Retailer: your-store-name" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Jane Smith",
    "gender": false,
    "birthDate": "1992-08-20",
    "contactNumber": "0987654321",
    "address": "456 Second Ave, District 3",
    "email": "jane@example.com",
    "organization": "Tech Corp"
  }'
```

---

## Categories

### List All Categories (Hierarchical)

```bash
curl -X GET "https://public.kiotapi.com/categories?hierachicalData=true" \
  -H "Retailer: your-store-name" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

### Create a Category

```bash
curl -X POST https://public.kiotapi.com/categories \
  -H "Retailer: your-store-name" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "categoryName": "Electronics",
    "parentId": null
  }'
```

---

## Webhooks

### Register a Webhook

```bash
curl -X POST https://public.kiotapi.com/webhooks \
  -H "Retailer: your-store-name" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "Webhook": {
      "Type": "product.update",
      "Url": "https://your-app.com/webhooks/kiotviet/products",
      "IsActive": true
    }
  }'
```

---

## Inventory

### Get Stock Levels by Branch

```bash
curl -X GET "https://public.kiotapi.com/productOnHands?branchIds=1,2&pageSize=100" \
  -H "Retailer: your-store-name" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

---

## Full Sync Pattern (Python)

```python
import requests
import time

class KiotVietClient:
    BASE_URL = "https://public.kiotapi.com"
    TOKEN_URL = "https://id.kiotviet.vn/connect/token"

    def __init__(self, client_id: str, client_secret: str, retailer: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self.retailer = retailer
        self.access_token = None
        self.token_expiry = 0

    def authenticate(self):
        response = requests.post(self.TOKEN_URL, data={
            "scopes": "PublicApi.Access",
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }, headers={"Content-Type": "application/x-www-form-urlencoded"})
        data = response.json()
        self.access_token = data["access_token"]
        self.token_expiry = time.time() + data["expires_in"] - 300

    def _headers(self):
        if time.time() >= self.token_expiry:
            self.authenticate()
        return {
            "Retailer": self.retailer,
            "Authorization": f"Bearer {self.access_token}",
        }

    def get_all(self, endpoint: str, params: dict = None) -> list:
        all_data = []
        current_item = 0
        page_size = 100

        while True:
            query = {"pageSize": page_size, "currentItem": current_item}
            if params:
                query.update(params)

            resp = requests.get(
                f"{self.BASE_URL}/{endpoint}",
                headers=self._headers(),
                params=query
            )
            result = resp.json()
            all_data.extend(result.get("data", []))

            current_item += page_size
            if current_item >= result.get("total", 0):
                break

        return all_data

# Usage
client = KiotVietClient("your-client-id", "your-secret", "your-store")
client.authenticate()

products = client.get_all("products", {"includeInventory": True})
orders = client.get_all("orders", {"includePayment": True})
customers = client.get_all("customers")
```
