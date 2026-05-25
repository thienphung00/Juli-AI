# KiotViet Customers API

## Base URL

```
https://public.kiotapi.com/customers
```

## Endpoints

### List Customers

```
GET /customers
```

**Query Parameters:**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `code` | string | No | Filter by customer code |
| `name` | string | No | Search by customer name |
| `contactNumber` | string | No | Filter by phone number |
| `lastModifiedFrom` | datetime | No | Filter from modification date |
| `pageSize` | int | No | Items per page (default: 20, max: 100) |
| `currentItem` | int | No | Pagination offset |
| `orderBy` | string | No | Sort field |
| `orderDirection` | string | No | `ASC` (default) or `DESC` |
| `includeRemoveIds` | boolean | No | Include deleted customer IDs |
| `includeCustomerGroup` | boolean | No | Include customer group data |
| `birthDate` | datetime | No | Filter by birth date |
| `groupId` | long | No | Filter by customer group ID |

**Response:**

```json
{
  "total": 100,
  "pageSize": 20,
  "data": [
    {
      "id": 200,
      "code": "KH001",
      "name": "Customer Name",
      "gender": true,
      "birthDate": "1990-05-15T00:00:00",
      "contactNumber": "0901234567",
      "address": "123 Street, District, City",
      "locationName": "Ho Chi Minh",
      "email": "customer@email.com",
      "organization": "Company ABC",
      "comment": "VIP customer",
      "taxCode": "0123456789",
      "debt": 500000.00,
      "totalInvoiced": 5000000.00,
      "totalPoint": 150,
      "totalRevenue": 4500000.00,
      "type": 1,
      "groups": "VIP,Regular",
      "retailerId": 1,
      "modifiedDate": "2024-01-15T10:30:00",
      "createdDate": "2023-06-01T08:00:00"
    }
  ],
  "removedIds": [],
  "timestamp": "2024-01-15T10:30:00"
}
```

---

### Get Customer by ID

```
GET /customers/{id}
```

### Get Customer by Code

```
GET /customers/code/{code}
```

---

### Create Customer

```
POST /customers
```

**Request Body:**

```json
{
  "code": "KH002",
  "name": "New Customer",
  "gender": true,
  "birthDate": "1985-03-20",
  "contactNumber": "0912345678",
  "address": "456 Avenue, Ward, District",
  "email": "newcustomer@email.com",
  "organization": "Company XYZ",
  "comment": "New VIP member",
  "taxCode": "9876543210"
}
```

**Notes:**
- `gender`: `true` = Male, `false` = Female
- `code`: Must be unique. If not provided, system auto-generates.

---

### Update Customer

```
PUT /customers/{id}
```

Same body structure as Create, with `id` in the URL path.

---

### Delete Customer

```
DELETE /customers/{id}
```

**Response:**
```json
{
  "message": "Xóa dữ liệu thành công"
}
```

## Customer Groups

### List Customer Groups

```
GET /customergroups
```

**Response:**
```json
{
  "total": 5,
  "data": [
    {
      "id": 1,
      "name": "VIP",
      "discount": 10.0,
      "retailerId": 1,
      "createdDate": "2023-01-01",
      "modifiedDate": "2024-01-15"
    }
  ]
}
```

## Customer Fields

| Field | Type | Description |
|---|---|---|
| `id` | long | Unique customer identifier |
| `code` | string | Customer code |
| `name` | string | Customer full name |
| `gender` | boolean | true=Male, false=Female |
| `birthDate` | datetime | Date of birth |
| `contactNumber` | string | Phone number |
| `address` | string | Full address |
| `locationName` | string | City/Province name |
| `email` | string | Email address |
| `organization` | string | Company/Organization name |
| `comment` | string | Notes about the customer |
| `taxCode` | string | Tax identification number |
| `debt` | decimal | Outstanding debt amount |
| `totalInvoiced` | decimal | Total invoiced amount |
| `totalPoint` | int | Loyalty points accumulated |
| `totalRevenue` | decimal | Total revenue from customer |
| `type` | int | Customer type |
| `groups` | string | Comma-separated group names |
| `retailerId` | int | Store ID |
| `modifiedDate` | datetime | Last modification timestamp |
| `createdDate` | datetime | Creation timestamp |
