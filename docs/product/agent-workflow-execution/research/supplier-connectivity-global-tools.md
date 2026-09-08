# Supplier connectivity without per-supplier integrations — global survey

Legend: **[D]** documented in the cited source · **[I]** inferred by me from the sources.

## 1. Platform-by-platform

### Shopify (native) + Stocky
- PO statuses are only **Draft** and **Ordered**; receiving/partial/closure live on a *linked inventory transfer*, deliberately keeping "the commercial agreement separate from the actual inventory movement" **[D]** — https://help.shopify.com/en/manual/products/inventory/purchase-orders/creating-purchase-orders , https://help.shopify.com/en/manual/products/inventory/purchase-orders/receiving-inventory
- Send channel: **save as PDF, send it yourself**. No automated notification, no acknowledgement capture **[D]**. Header fields: supplier, supplier currency (auto-converted), payment terms, optional reference **[D]**.
- Receiving: per line **accept / reject / cancel**, several actions per line, reject-reason notes, per-shipment cost adjustments, **In progress → Transferred** once expected qty is accounted for; multi-shipment supported **[D]**.
- Stocky (retires 31 Aug 2026) added Draft/Ordered/**Partial**/Received/Closed, backorders, barcode receiving, PO email as PDF or CSV **[D]** https://support.retailorbit.com/hc/en-us/articles/28370508634011-Stocky-Purchase-Orders-Guide
- **No PurchaseOrder object/query/mutation in the Admin API as of the 2026-07 RC** **[D]** — https://community.shopify.dev/t/feature-request-expose-the-existing-purchase-orders-to-the-admin-graphql-api/35229 . So any Shopify-side PO product must own its own PO store **[I]**.
- Document-in apps: *Unload* uses **AI to extract products/images/variants from supplier invoices and catalogs** **[D]** https://apps.shopify.com/unload ; *Order – Scan Documents* OCRs order numbers **[D]**. I found **no** mainstream app that reads a supplier *inbox* and updates POs **[I]**.

### The ERP/IMS cohort
| Tool | Send channel | Ack capture | Receiving |
|---|---|---|---|
| Inventory Planner | download PDF **or email PO**; approval thresholds gate auto-POs **[D]** https://help.inventory-planner.com/en/articles/588988-purchase-orders | none native **[I]** | partial **[I]** |
| Cin7 Core | PO email; approval workflow with an explicit **Rejected** state you set when the supplier rejects **[D]** https://help.core.cin7.com/hc/en-us/articles/9034494222863-Purchase-Order-Approval | human-entered status **[D]** | receive, then invoice separately **[D]** |
| Cin7 Omni | native EDI + EDI/3PL portal, receipts confirmed on a scheduler **[D]** https://help.omni.cin7.com/hc/en-us/articles/9128544939407-Access-the-EDI-3PL-Portal | EDI 855-class, big retail partners only **[D]** | 3PL-synced **[D]** |
| Unleashed | **email automation**; "View Email Log" proves it was sent **[D]** https://support.unleashedsoftware.com/hc/en-us/articles/33614074827545-How-can-I-check-if-a-Purchase-Order-has-been-sent-to-the-supplier | *send* logged, not *ack* **[D]** | supplier returns is a distinct flow **[D]** |
| Linnworks | email from the PO screen **[D]** https://docs.linnworks.com/articles/documentation/purchase-orders | none **[D]** | Pending → Open → **Partially Delivered** **[D]** |
| Zoho Inventory | email PO **[D]** https://www.zoho.com/us/inventory/help/purchase-orders/purchase-order-creation.html | manual **[I]** | explicit **Partial receive** creating a Purchase Receive doc; receive-then-bill default **[D]** https://www.zoho.com/us/inventory/kb/purchase-order/po-receives.html |
| Katana | emails PO/RFQ, tracks "sent" **[D]** https://support.katanamrp.com/en/articles/5945006-how-to-send-purchase-orders-po-or-request-for-quotes-rfq-to-suppliers | none **[D]** | partial **[I]** |
| **Odoo Purchase** | **Draft (RFQ) → RFQ Sent → Purchase Order** **[D]** https://www.odoo.com/documentation/19.0/applications/inventory_and_mrp/purchase/manage_deals/rfq.html | **strongest SMB ack found**: vendor opens a portal link, may edit unit price, **Accept & Sign**; chatter logs "Vendor has acknowledged it" with signature + timestamp **[D]** | under-receipt spawns a **backorder** doc **[D]** https://www.odoo.com/documentation/user/13.0/purchase/purchases/rfq/reception.html |
| Brightpearl | EDI 850/855/856 **[D]** https://www.brightpearl.com/blog/secrets-of-the-advanced-shipping-notice-or-edi-856 | 855 = accept as-is / accept-with-change / reject **[D]** https://www.spscommerce.com/edi-document/edi-855-purchase-order-acknowledgment/ | ASN auto-updates inventory **[D]** |
| SKULabs / inFlow | email PO **[D]** | none **[I]** | **barcode scan-receiving**, per-item accept + qty, explicit Partial receive **[D]** https://www.skulabs.com/help/en/articles/4144023-how-to-receive-purchase-orders , https://www.inflowinventory.com/support/cloud/how-do-i-partially-receive-products-on-a-purchase-order-in-inflow-cloud |
| QuickBooks Commerce | **dead** — closed to new customers Jun 2022, shut 31 Aug 2023, ~10k businesses displaced **[D]** https://www.unleashedsoftware.com/blog/quickbooks-commerce-sunset/ | | |

**The pattern:** across ten tools, exactly one (Odoo, via a portal link) captures machine-readable supplier acknowledgement without EDI. Every other treats ack as **a status a human sets after reading an email or a chat** **[I]**.

### Supplier portals as a pattern
Cin7 and Unleashed sell portals as add-on modules **[D]** https://www.cin7.com/features/sales/b2b-online-stores/ . The enterprise version fails on cost: Ariba suppliers transact free only to ~5 documents and $50,000 per buyer per year, then must buy a paid account, and "adoption stalls precisely because their supplier base… is unwilling to absorb Ariba Network fees" **[D]** — https://redresscompliance.com/sap-ariba-negotiations-managing-transaction-fees-volume-tiers-and-network-costs/ , https://www.tutorialspoint.com/sap_ariba/sap_ariba_supplier_membership_fees.htm . **A portal needing registration or fees will not reach a long-tail TikTok Shop supplier; a signed no-login link (Odoo's shape) might** **[I]**.

### AI document capture
- **Zoho Autoscan**: unique inbound email address per org; vendors email bills in; extracts header (vendor, bill no., dates, totals) **and** line items (description, qty, unit price, total); **pre-populates a draft bill rather than posting one**, with the confidence score kept as a per-bill custom field **[D]** — https://www.zoho.com/inventory/help/documents/documents.html , https://invoicedataextraction.com/blog/zoho-books-bill-automation
- **Hubdoc/Xero**: unique `@app.hubdoc.com` address; extracts supplier, date, invoice no., total; **explicitly does not extract line items** — typed manually or reused via per-supplier rules; output is a **draft bill with the source doc attached**, published on one human click **[D]** — https://central.xero.com/s/article/About-data-extraction-in-Hubdoc-US-SG-SA-ROW
- **Rossum**: confidence thresholds auto-pass eligible docs, low-confidence fields **highlighted for immediate verification**, correction separated from business approval **[D]** — https://www.g2.com/products/rossum/reviews . **Nanonets** ships pre-trained PO and **delivery-note** models **[D]** — https://docs.nanonets.com/docs/purchase-order-model , https://nanonets.com/document-ocr/delivery-note

### Messaging as a channel
Shipping today, mostly India/SEA B2B. **HublerX** runs NLP over WhatsApp text, **voice notes and photos**, extracts product refs/qty/delivery, posts confirmed orders to the ERP and WhatsApps a confirmation back **[D]** https://www.hublerx.ai/b2b-whatsapp-ordering-app ; **B2Bee** and **DialogTab** do the same **[D]** https://www.b2bee.net/whatsapp-b2b-ecommerce , https://dialogtab.com/sectors/wholesale . All are **seller-side**; the buyer-side mirror is nearly empty **[I]**. LineNow names that gap: WhatsApp confirmations "stay in chat threads [and] don't update the purchase order," so closing the loop means reading the reply, extracting structured changes and applying them to the living PO — while "the channel delivers the message; a responsible person still decides whether to accept the supplier's terms" **[D]** https://www.linenow.co/blog/guides/whatsapp-supplier-ordering-smb

### EDI/API reality
APIs exist for **1688/Alibaba** — products, orders, inventory, status/tracking **[D]** https://www.opentopcart.com/understanding-the-1688-api-a-key-tool-for-e-commerce-integration/ , https://developer.alibaba.com/docs/doc.htm?treeId=684&articleId=118416&docType=1 . EDI exists only where a **large retailer mandates it** (Walmart/Target/Costco) **[D]** https://www.cin7.com/solutions/omni/ . The long tail — factory, sourcing agent, local wholesaler — is chat/email/PDF only **[I]**.

## 2. The shared data model

**Supplier**: id, name, contacts (email/phone/**messaging handle**), address, currency, payment terms, lead time, MOQ, per-SKU supplier cost + **supplier SKU** (Cin7 "product suppliers", Linnworks multi-supplier-per-item) **[D]**.

**PO header**: supplier, PO number, reference, currency, payment terms, expected arrival, destination, totals, landed-cost adjustments. **Lines**: SKU, supplier SKU, qty ordered, unit cost, tax, qty received, qty outstanding.

**Canonical states** (union of all the above): `draft → sent/ordered → acknowledged (accept-as-is | accept-with-changes | rejected) → partially_received → received → closed`, with `cancelled` and `backorder` as branches. Anchors: Odoo Draft/RFQ Sent/PO; EDI 855's three ack outcomes; Linnworks Pending/Open/Partially Delivered; Zoho Partially Received; Stocky Draft/Ordered/Partial/Received/Closed — all **[D]**.

**Receipt is a separate entity, not a PO field** — Shopify's transfer, Zoho's Purchase Receive, Odoo's backorder **[D]**. Receipt: id, PO ref, arrival date, per-line accepted/rejected/cancelled qty + reason note, source document, cost adjustments. Model it that way from day one; retrofitting multi-shipment onto a `qty_received` column is the classic trap **[I]**.

## 3. Universal bridge ranking (traffic captured ÷ engineering)

| Rank | Channel | Cost | Traffic captured | Failure mode |
|---|---|---|---|---|
| **1** | **Manual receiving slip** — tap quantities against an expected PO | days | 100%; every other channel degrades into it | operator skips it when busy; must be <30s |
| **2** | **Photo/OCR of packing slip or invoice** → prefilled receipt | 1–2 wks on a hosted model | very high for CN/SEA sourcing — a paper slip always exists | glare, handwriting, CJK; supplier SKU ≠ your SKU — the real cost is the **SKU-matching layer**, reused by every later channel |
| **3** | **CSV/Excel price-list & PO import** | days | high for cost/catalogue updates, ~0 for receipts | column drift per supplier; needs mapping remembered per supplier (Hubdoc's "supplier rules" **[D]**) |
| **4** | **Email-forward parsing** — unique inbound address (Zoho/Hubdoc **[D]**) | 1–2 wks: inbound webhook + the same extractor as #2 | medium-high in the West, lower for CN/SEA sourcing | reply threading and quoted text; odd attachment formats |
| **5** | **Messaging parse** (WhatsApp/LINE/Zalo/Telegram) | 2–4 wks each + platform approval; Zalo and LINE need separate business APIs | *highest real traffic* for TikTok Shop sourcing, but priciest per channel | order split across many messages, voice notes, images, code-switching, no PO reference |
| **6** | **Supplier portal / magic link** (Odoo shape) | 2–3 wks | only if suppliers click; **zero if login or fees are required** (Ariba **[D]**) | non-adoption, not bugs |
| **7** | **EDI / supplier API** | months per partner | ~0% of the long tail | only 1688/Alibaba and retailer-mandated partners |

**Lowest-cost universal bridge: one intake pipe for a `Receipt`/`Ack` with a pluggable *source*; v1 sources are (a) manual and (b) photo/OCR.** Every later channel — email, chat, portal, EDI — is then a source adapter emitting the same envelope `{parsed_fields, confidence, field_confidences, source_doc_ref, raw_text}`, reusing one SKU matcher and one confirm UI **[I]**. The envelope and the matcher are the moat, not any single channel.

## 4. The human-confirm step (the pattern to keep)

Every credible product does the same thing, and none auto-post:
- **prefill, don't post** — Zoho pre-populates a *draft* bill; Hubdoc publishes only on a human click **[D]**;
- **field-level confidence, not document-level** — Rossum highlights low-confidence fields and separates *data correction* from *business authorization*; Zoho persists a per-bill confidence score **[D]**;
- **discrepancy is a first-class outcome, not an error** — per-line accept/reject/cancel with a reason note (Shopify), backorder for the remainder (Odoo) **[D]**;
- **provenance survives** — source doc attached (Hubdoc), email log (Unleashed), chatter entry with signature and timestamp (Odoo) **[D]**;
- **changed terms need explicit acceptance** — EDI 855 makes "accepted with modifications" its own code **[D]**; LineNow states the chat norm: a person decides whether to accept the supplier's terms **[D]**.

For Juli: a parse yields a **proposed receipt/ack diff against the live PO**, rendered as a prefilled form with low-confidence fields flagged and the source photo/message beside it; the seller taps Confirm; the PO transitions. That is the approval gate we already have — a source adapter plus a diff, not a new interaction model.
