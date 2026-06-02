import unicodedata
from dataclasses import dataclass

_POSITIVE_KEYWORDS: set[str] = {
    "tốt", "tuyệt", "tuyệt vời", "đẹp", "thích", "ưng", "ưng ý",
    "chất lượng cao", "xuất sắc", "hài lòng", "ổn", "nhanh",
    "giá rẻ", "đáng mua", "yêu", "hay", "tốt lắm", "rất tốt",
    "rất đẹp", "rất thích", "giao nhanh", "chất lượng",
}

_NEGATIVE_KEYWORDS: set[str] = {
    "tệ", "xấu", "dở", "chán", "thất vọng", "kém", "hỏng",
    "không tốt", "rẻ tiền", "chậm", "lỗi", "trả lại",
    "quá tệ", "không mua", "không ưng", "dở tệ", "quá dở",
    "không hài lòng", "mất tiền", "lừa đảo",
}


def _normalize(text: str) -> str:
    return unicodedata.normalize("NFC", text.lower().strip())


def _classify_one(text: str) -> str:
    normed = _normalize(text)
    pos_hits = sum(1 for kw in _POSITIVE_KEYWORDS if kw in normed)
    neg_hits = sum(1 for kw in _NEGATIVE_KEYWORDS if kw in normed)

    if pos_hits > neg_hits:
        return "positive"
    if neg_hits > pos_hits:
        return "negative"
    return "neutral"


@dataclass
class SentimentResult:
    total: int
    positive_count: int
    negative_count: int
    neutral_count: int
    overall: str


def analyze_comments(comments: list[str]) -> SentimentResult:
    if not comments:
        return SentimentResult(
            total=0, positive_count=0, negative_count=0,
            neutral_count=0, overall="neutral",
        )

    pos = neg = neu = 0
    for c in comments:
        label = _classify_one(c)
        if label == "positive":
            pos += 1
        elif label == "negative":
            neg += 1
        else:
            neu += 1

    total = len(comments)
    if pos > neg and pos > neu:
        overall = "positive"
    elif neg > pos and neg > neu:
        overall = "negative"
    elif pos > 0 and neg > 0:
        overall = "mixed"
    else:
        overall = "neutral"

    return SentimentResult(
        total=total,
        positive_count=pos,
        negative_count=neg,
        neutral_count=neu,
        overall=overall,
    )
