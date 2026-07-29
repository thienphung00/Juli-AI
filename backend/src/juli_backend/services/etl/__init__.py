from juli_backend.services.etl.channels import DLQ_CHANNEL, RAW_CHANNELS
from juli_backend.services.etl.record import IngestRecord, KafkaRecord
from juli_backend.services.etl.transform import transform_for_channel, transform_for_topic

_LAZY_EXPORTS = {
    "EtlConsumer": "juli_backend.services.etl.consumer",
    "ProcessOutcome": "juli_backend.services.etl.consumer",
}


def __getattr__(name: str):
    module_path = _LAZY_EXPORTS.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    module = importlib.import_module(module_path)
    return getattr(module, name)


__all__ = [
    "DLQ_CHANNEL",
    "RAW_CHANNELS",
    "EtlConsumer",
    "IngestRecord",
    "KafkaRecord",
    "ProcessOutcome",
    "transform_for_channel",
    "transform_for_topic",
]
