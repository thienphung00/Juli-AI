# KiotViet Orders API

## Base URL

```
https://public.kiotapi.com/orders
```

## Prerequisites

- The "Allow Orders" setting must be enabled in KiotViet.
- If using delivery features, "Use delivery feature" setting must be enabled.
- If "Do not allow changing sale time" is enabled, time-related POST/PUT will be restricted.

## Endpoints

### List Orders

```
GET /orders
```

**Query Parameters:**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `branchIds` | int[] | No | Filter by branch IDs |
| `customerIds` | long[] | No | Filter by customer IDs |
| `customerCode` | string | No | Filter by customer code |
| `status` | int[] | No | Filter by order status |
| `includePayment` | boolean | No | Include payment details |
| `includeOrderDelivery` | boolean | No | Include delivery info |
| `lastModifiedFrom` | datetime | No | Filter from modification date |
| `toDate` | datetime | No | Filter to modification date |
| `pageSize` | int | No | Items per page (default: 20, max: 100) |
| `currentItem` | int | No | Pagination offset |
| `orderBy` | string | No | Sort field |
| `orderDirection` | string | No | `ASC` (default) or `DESC` |
| `createdDate` | datetime | No | Filter by creation date |
| `saleChannelId` | int | No | Filter by sales channel |

**Response:**

```json
{
  "total": 50,
  "pageSize": 20,
  "data": [
    {
      "id": 1001,
      "code": "DH000001",
      "purchaseDate": "2024-01-15T14:30:00",
      "branchId": 1,
      "branchName": "Main Store",
      "soldById": 5,
      "soldByName": "Staff A",
      "customerId": 200,
      "customerCode": "KH001",
      "customerName": "Customer Name",
      "total": 500000.00,
      "totalPayment": 200000.00,
      "discountRatio": 10.0,
      "discount": 50000.00,
      "status": 1,
      "statusValue": "Active",
      "description": "Order note",
      "usingCod": false,
      "totalTax": 50000.00,
      "saleChannelId": null,
      "modifiedDate": "2024-01-15T14:30:00",
      "createdDate": "2024-01-15T14:30:00",
      "orderDetails": [
        {
          "productId": 12345,
          "productCode": "SP001",
          "productName": "Product Name",
          "isMaster": true,
          "quantity": 2.0,
          "price": 250000.00,
          "discountRatio": 5.0,
          "discount": 12500.00,
          "note": "Item note"
        }
      ],
      "payments": [
        {
          "id": 501,
          "code": "PT001",
          "amount": 200000.00,
          "method": "Cash",
          "status": 1,
          "statusValue": "Completed",
          "transDate": "2024-01-15T14:30:00",
          "bankAccount": null,
          "accountId": null
        }
      ],
      "orderDelivery": {
        "deliveryCode": "GH001",
        "type": 1,
        "price": 30000.00,
        "receiver": "Receiver Name",
        "contactNumber": "0901234567",
        "address": "123 Street, District",
        "locationId": 1,
        "locationName": "Ho Chi Minh",
        "weight": 1.5,
        "length": 30.0,
        "width": 20.0,
        "height": 10.0,
        "partnerDeliveryId": 3
      }
    }
  ]
}
```

---

### Get Order by ID

```
GET /orders/{id}
```

### Get Order by Code

```
GET /orders/code/{code}
```

---

### Create Order

```
POST /orders
```

**Request Body:**

```json
{
  "isApplyVoucher": false,
  "purchaseDate": "2024-01-15T14:30:00",
  "branchId": 1,
  "soldById": 5,
  "cashierId": 5,
  "discount": 50000,
  "description": "Order notes",
  "method": "Cash",
  "totalPayment": 200000,
  "accountId": null,
  "makeInvoice": false,
  "saleChannelId": null,
  "orderDetails": [
    {
      "productId": 12345,
      "productCode": "SP001",
      "productName": "Product Name",
      "quantity": 2.0,
      "price": 250000.00,
      "discount": 12500.00,
      "discountRatio": 5.0,
      "note": "Item note",
      "OrderDetailTaxs": [
        { "TaxId": 4 }
      ]
    }
  ],
  "orderDelivery": {
    "deliveryCode": "GH001",
    "type": 1,
    "price": 30000.00,
    "receiver": "Receiver Name",
    "contactNumber": "0901234567",
    "address": "123 Street",
    "locationId": 1,
    "locationName": "Ho Chi Minh",
    "weight": 1.5,
    "length": 30.0,
    "width": 20.0,
    "height": 10.0,
    "partnerDeliveryId": 3,
    "expectedDelivery": "2024-01-18T14:30:00",
    "partnerDelivery": {
      "code": "GHN",
      "name": "GHN Express",
      "address": "456 Avenue",
      "contactNumber": "1900xxxx",
      "email": "contact@ghn.vn"
    }
  },
  "customer": {
    "id": 200,
    "code": "KH001",
    "name": "Customer Name",
    "gender": true,
    "birthDate": "1990-05-15",
    "contactNumber": "0901234567",
    "address": "789 Road",
    "email": "customer@email.com",
    "comment": "VIP customer"
  },
  "surchages": [
    {
      "id": 1,
      "code": "SC001",
      "price": 10000.00
    }
  ]
}
```

**Notes:**
- `cashierId`: If not provided, defaults to Admin as order creator.
- `accountId`: Required when payment method is `TRANSFER` or `CARD`.
- `makeInvoice`: If true, creates an invoice from the order with a payment receipt.

**Partner Headers (for integrations):**
- From MyKiot: `Partner: MyKiot`
- From KV Sync: `Partner: KVSync`

---

### Update Order

```
PUT /orders/{id}
```

Same body structure as Create. The order ID is passed in the URL.

---

### Cancel Order

```
PUT /orders/{id}
```

Set appropriate status to cancel.

## Tax IDs Reference

### Deduction Method (Khấu trừ)

| TaxId | Rate |
|---|---|
| 1 | VAT 0% |
| 2 | VAT 5% |
| 3 | VAT 8% |
| 4 | VAT 10% |
| 5 | KCT (Not subject to tax) |
| 12 | KKKNT (Non-declarable) |

### Direct Method (Trực tiếp)

| TaxId | Rate |
|---|---|
| 6 | VAT 1% |
| 7 | VAT 2% |
| 8 | VAT 3% |
| 9 | VAT 5% |
| 64 | 0% VAT + 5% Personal Income Tax |
| 65 | 0% VAT + 1.5% PIT |
| 66 | 0% VAT + 2% PIT |

## Payment Methods

| Value | Description |
|---|---|
| `Cash` | Cash payment |
| `Card` | Card payment |
| `Transfer` | Bank transfer |
| `Voucher` | Voucher payment |

## Voucher Payment

```json
{
  "Payments": [
    {
      "Method": "Voucher",
      "MethodStr": "Voucher",
      "Amount": 50000,
      "Id": -1,
      "AccountId": null,
      "VoucherId": 30996,
      "VoucherCampaignId": 30087
    }
  ]
}
```

## Pricing Mode

| Value | Description |
|---|---|
| null | Direct pricing |
| 0 | Pre-tax pricing |
| 1 | Post-tax pricing |
