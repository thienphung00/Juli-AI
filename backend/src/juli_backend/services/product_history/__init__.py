"""Product history, promotions, external changes and run baselines (fast track P23, D30.1/D30.4).

- ``normalize`` -- pure: product detail → snapshot fields, hashes, diff.
- ``store`` -- snapshots and ``external_changes`` (Juli-write matching).
- ``promotions`` -- activity upserts, webhook 63 / 39 parsing.
- ``job`` -- the daily snapshot + promotion sweep and the webhook re-reads (TikTok reads).
- ``webhooks`` -- webhooks 15 / 16 / 18 / 63 / 39 → an enqueued re-read.
- ``replay`` -- replays the stored raw deliveries of those types.
- ``baselines`` -- ``run_baselines`` at approval and at execution start.
- ``overlap`` -- external changes overlapping a measurement window.
"""
