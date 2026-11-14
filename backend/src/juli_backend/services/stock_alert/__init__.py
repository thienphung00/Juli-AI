"""Stock alert / stock-out prevention for Shopee shops (Part S, P100).

Pure core: ``forecast`` (units / day, days left), ``stock_basis`` (which stock figure at send
time), ``eligibility`` (who gets an alert, triggers, order), ``compose`` (the e-mail). Around it:
``history`` (the per-variation stock history written on ``item_snapshot`` ingest), ``settings``
(shop status / days, the per-SKU "Theo dõi" switch), ``data`` (the facts from the database),
``recipients``, ``links`` (signed unsubscribe link), ``mail`` (SMTP), ``job`` (the 07:00 GMT+7
run) and ``cards`` (what an untracked variation does to the recommendation cards).
"""
