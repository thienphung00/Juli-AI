from juli_backend.ai.recommendations.classifier import (
    TrendTier,
    build_recommendation_message,
    classify_product_trend,
)
from juli_backend.ai.recommendations.engine import (
    HostProductMatch,
    PriceDirectionSuggestion,
    ProductPushSuggestion,
    ProductRecommendation,
    StreamOptimizationSuggestion,
    get_host_product_matching,
    get_price_direction_suggestion,
    get_product_push_suggestions,
    get_stream_optimization,
    get_trending_product_recommendation,
)

__all__ = [
    "HostProductMatch",
    "PriceDirectionSuggestion",
    "ProductPushSuggestion",
    "ProductRecommendation",
    "StreamOptimizationSuggestion",
    "TrendTier",
    "build_recommendation_message",
    "classify_product_trend",
    "get_host_product_matching",
    "get_price_direction_suggestion",
    "get_product_push_suggestions",
    "get_stream_optimization",
    "get_trending_product_recommendation",
]
