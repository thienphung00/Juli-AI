"""A deterministic synthetic Shopee shop ("Dữ liệu mẫu") for the ISV demo client (P100 S2-A).

``generator`` makes Connector-shaped ``IngestBody`` posts (pure, fixed seed); ``loader`` is the CLI
that writes them as JSONL or ingests them in-process into a LOCAL database through the same
gateway a real Connector hits. See ``fasttrack/contracts/p100-s2-demo.md`` (section S2-A result).
"""
