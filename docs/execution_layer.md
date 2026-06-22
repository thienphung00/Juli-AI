# Execution Layer

> **Tier 1 — workflow taxonomy.** Read [`EXECUTION.md`](../EXECUTION.md) first.  
> **Owns:** workflow IDs, action ownership, routing rules. **Does not own:** UI tabs (ADR-014), KPI charts (`visual_layer.md`).

Authoritative workflow → action catalog (ADR-011). Approval-gated execution only.

## Catalog & rules

Catalog (Catalog expansion is a **separate** workflow from listing edits):

### Update Product Listing
- Update Product Title
- Update Product Description
- Update Product Images
- Adjust Product Price

### Create New Product Listing
- Generate Listing Title
- Generate Listing Description
- Generate Product Images
- Set Initial Price
- Publish Product

### Create Product Bundle *(catalog expansion — its own workflow, not part of Update Product Listing)*
- Select Bundle Products
- Generate Bundle Title
- Generate Bundle Description
- Generate Bundle Images
- Set Bundle Price
- Publish Bundle Listing

## Ads

### Increase Ad Budget
- Increase Campaign Budget
- Increase Daily Spend Limit
- Activate Campaign

### Reduce Ad Spend
- Pause Campaign
- Reduce Bid
- Reallocate Budget

## Inventory

### Replenish Inventory
- Create Restock Order
- Adjust Reorder Quantity
- Notify Purchasing Team

### Clear Excess Inventory *(bundle creation removed — now its own workflow)*
- Reduce Product Price
- Create Promotion

## Operations

### Accelerate Order Fulfillment *(sole owner of Batch Ship Orders)*
- Prioritize Shipment Queue
- Batch Ship Orders
- Update Order Status

### Prevent Order Cancellations
- Reserve Inventory
- Pause Affected Listings
- Sync Inventory

## Customer Service

### Resolve Recurring Customer Complaints *(Batch Ship Orders removed — belongs to Accelerate Order Fulfillment)*
- Identify Complaint Cluster
- Notify Customers
- Update Fulfillment Settings
- Escalate Operational Issue

### Prevent Product Returns *(listing-edit actions removed — they belong to Update Product Listing)*
- Send Clarification Message
- Provide Usage Instructions
- Offer Exchange
- Tag Return Reason

## Overlap resolution (applied)

| Action | Sole owner | Removed from |
|--------|-----------|--------------|
| Bundle creation | Create Product Bundle | Update Product Listing · Clear Excess Inventory |
| Batch Ship Orders | Accelerate Order Fulfillment | Resolve Recurring Customer Complaints |
| Update Product Description / Images | Update Product Listing | Prevent Product Returns |
