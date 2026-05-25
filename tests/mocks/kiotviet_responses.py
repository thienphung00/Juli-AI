"""Reusable mock response payloads for KiotViet API tests."""

from __future__ import annotations

TOKEN_RESPONSE = {
    "access_token": "mock-jwt-token-abc123",
    "expires_in": 86400,
    "token_type": "Bearer",
}

PRODUCT_ITEM = {
    "id": 12345,
    "code": "SP001",
    "barCode": "8934567890123",
    "name": "Test Product",
    "fullName": "Test Product - Size M",
    "categoryId": 1,
    "categoryName": "Category A",
    "allowsSale": True,
    "hasVariants": False,
    "basePrice": 150000.0,
    "unit": "piece",
    "isActive": True,
    "modifiedDate": "2024-01-15T10:30:00",
    "createdDate": "2024-01-01T08:00:00",
}

PRODUCTS_LIST_RESPONSE = {
    "total": 1,
    "pageSize": 20,
    "data": [PRODUCT_ITEM],
}

PRODUCTS_PAGINATED_PAGE_1 = {
    "total": 150,
    "pageSize": 100,
    "data": [{"id": i, "code": f"SP{i:03d}", "name": f"Product {i}"} for i in range(100)],
}

PRODUCTS_PAGINATED_PAGE_2 = {
    "total": 150,
    "pageSize": 100,
    "data": [{"id": i, "code": f"SP{i:03d}", "name": f"Product {i}"} for i in range(100, 150)],
}

ORDER_ITEM = {
    "id": 1001,
    "code": "DH000001",
    "purchaseDate": "2024-01-15T14:30:00",
    "branchId": 1,
    "branchName": "Main Store",
    "customerId": 200,
    "customerName": "Customer Name",
    "total": 500000.0,
    "totalPayment": 200000.0,
    "status": 1,
    "statusValue": "Active",
    "orderDetails": [
        {
            "productId": 12345,
            "productCode": "SP001",
            "productName": "Test Product",
            "quantity": 2.0,
            "price": 250000.0,
        }
    ],
}

ORDERS_LIST_RESPONSE = {
    "total": 1,
    "pageSize": 20,
    "data": [ORDER_ITEM],
}

CUSTOMER_ITEM = {
    "id": 200,
    "code": "KH001",
    "name": "Customer Name",
    "gender": True,
    "contactNumber": "0901234567",
    "address": "123 Street",
    "email": "customer@email.com",
    "debt": 0.0,
    "totalRevenue": 4500000.0,
    "modifiedDate": "2024-01-15T10:30:00",
    "createdDate": "2023-06-01T08:00:00",
}

CUSTOMERS_LIST_RESPONSE = {
    "total": 1,
    "pageSize": 20,
    "data": [CUSTOMER_ITEM],
}

CUSTOMER_GROUPS_RESPONSE = {
    "total": 1,
    "data": [
        {
            "id": 1,
            "name": "VIP",
            "discount": 10.0,
            "retailerId": 1,
        }
    ],
}

INVENTORY_ITEM = {
    "id": 12345,
    "code": "SP001",
    "inventories": [
        {"branchId": 1, "onhand": 50.0, "reserved": 5.0},
    ],
}

INVENTORY_LIST_RESPONSE = {
    "total": 1,
    "pageSize": 100,
    "data": [INVENTORY_ITEM],
}

ATTRIBUTES_RESPONSE = [
    {
        "name": "Color",
        "id": 1,
        "attributeValues": [
            {"value": "Red", "attributeId": 1},
            {"value": "Blue", "attributeId": 1},
        ],
    },
]

DELETE_SUCCESS_RESPONSE = {"message": "Xóa dữ liệu thành công"}

ERROR_400_RESPONSE = {
    "responseStatus": {
        "errorCode": "ValidationError",
        "message": "Invalid request",
        "errors": [
            {"errorCode": "Required", "fieldName": "name", "message": "Name is required"},
        ],
    }
}

ERROR_401_RESPONSE = {
    "responseStatus": {
        "errorCode": "Unauthorized",
        "message": "Invalid or expired token",
        "errors": [],
    }
}

ERROR_404_RESPONSE = {
    "responseStatus": {
        "errorCode": "NotFound",
        "message": "Resource not found",
        "errors": [],
    }
}

ERROR_429_RESPONSE = {
    "responseStatus": {
        "errorCode": "TooManyRequests",
        "message": "Rate limit exceeded",
        "errors": [],
    }
}

ERROR_500_RESPONSE = {
    "responseStatus": {
        "errorCode": "InternalError",
        "message": "Internal server error",
        "errors": [],
    }
}
