"""The six synthetic products (household goods, an invented brand) and the id ranges.

Nothing here is a real shop's name, price or id: the brand "Hiên Nhà" and every product are made
up for the demo client. Prices are VND, as the Connector posts them.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Seller Centre shop ids of sample shops. Real Shopee ids are at most 10 digits, so a 12-digit id
#: starting 99 never collides with one. The loader creates and writes ONLY shops in this range.
SAMPLE_SHOPEE_SHOP_ID_MIN = 990_000_000_000
SAMPLE_SHOPEE_SHOP_ID_MAX = 990_000_000_999
SAMPLE_SHOPEE_SHOP_ID = SAMPLE_SHOPEE_SHOP_ID_MIN + 1
SAMPLE_SHOP_NAME = "Dữ liệu mẫu"

#: Item / model ids are synthetic too (13 digits, 91 prefix).
ITEM_ID_BASE = 9_100_000_000_000


@dataclass(frozen=True)
class Variation:
    """``cost`` is the giá vốn of ONE single item: the profit engine multiplies it by the pack
    count a "Combo N" name states, so the Combo 3 variation carries the single bottle's cost."""

    model_id: str
    name: str
    sku: str
    price: int
    cost: int
    stock: int


@dataclass(frozen=True)
class Product:
    item_id: str
    name: str
    parent_sku: str
    variations: tuple[Variation, ...]
    variation_weights: tuple[int, ...]
    #: weights of 1, 2, 3, 4 units per line
    qty_weights: tuple[int, ...]
    base_views: int
    ctr: float
    cvr: float
    in_combo: bool
    #: index of the ad campaign that promotes the product (None = not advertised)
    campaign: int | None
    sold_before: int


def _v(
    item: int, n: int, name: str, price: int, cost_pct: float, stock: int, code: str
) -> Variation:
    return Variation(
        model_id=str(ITEM_ID_BASE + item * 100 + n),
        name=name,
        sku=f"{code}-{n}",
        price=price,
        cost=round(price * cost_pct / 500) * 500,
        stock=stock,
    )


PRODUCTS: tuple[Product, ...] = (
    Product(
        str(ITEM_ID_BASE + 1),
        "Nước rửa chén sinh học Hiên Nhà chai 500ml",
        "HN-NRC",
        (
            _v(1, 1, "500ml hương chanh", 59_000, 0.46, 640, "HN-NRC"),
            _v(1, 2, "500ml hương trà xanh", 59_000, 0.46, 520, "HN-NRC"),
            _v(1, 3, "Combo 3 chai", 165_000, 0.46 * 59 / 165, 210, "HN-NRC"),
        ),
        (5, 3, 2),
        (45, 40, 12, 3),
        1450,
        0.040,
        0.050,
        True,
        0,
        2_100,
    ),
    Product(
        str(ITEM_ID_BASE + 2),
        "Khăn lau đa năng Hiên Nhà set 5 khăn",
        "HN-KLD",
        (
            _v(2, 1, "Bộ 5 khăn xám", 79_000, 0.42, 480, "HN-KLD"),
            _v(2, 2, "Bộ 5 khăn pastel", 79_000, 0.42, 430, "HN-KLD"),
        ),
        (3, 2),
        (55, 32, 10, 3),
        1100,
        0.038,
        0.048,
        True,
        0,
        1_650,
    ),
    Product(
        str(ITEM_ID_BASE + 3),
        "Túi đựng rác tự hủy sinh học Hiên Nhà cuộn 30 túi",
        "HN-TDR",
        (
            _v(3, 1, "Size M 45x55cm", 49_000, 0.47, 700, "HN-TDR"),
            _v(3, 2, "Size L 55x65cm", 59_000, 0.47, 600, "HN-TDR"),
        ),
        (3, 2),
        (40, 38, 17, 5),
        1250,
        0.042,
        0.050,
        True,
        0,
        2_800,
    ),
    Product(
        str(ITEM_ID_BASE + 4),
        "Găng tay cao su Hiên Nhà dày dặn không mùi",
        "HN-GTC",
        (
            _v(4, 1, "Size M", 69_000, 0.45, 390, "HN-GTC"),
            _v(4, 2, "Size L", 69_000, 0.45, 370, "HN-GTC"),
        ),
        (1, 1),
        (62, 28, 8, 2),
        800,
        0.036,
        0.046,
        False,
        1,
        980,
    ),
    Product(
        str(ITEM_ID_BASE + 5),
        "Hộp đựng thực phẩm thủy tinh Hiên Nhà nắp kín",
        "HN-HDT",
        (
            _v(5, 1, "Hộp 640ml", 169_000, 0.50, 260, "HN-HDT"),
            _v(5, 2, "Hộp 1040ml", 219_000, 0.50, 220, "HN-HDT"),
            _v(5, 3, "Bộ 3 hộp", 459_000, 0.50, 90, "HN-HDT"),
        ),
        (4, 3, 1),
        (74, 20, 5, 1),
        600,
        0.034,
        0.040,
        False,
        1,
        640,
    ),
    Product(
        str(ITEM_ID_BASE + 6),
        "Bình xịt vệ sinh đa năng Hiên Nhà chai 500ml",
        "HN-BXV",
        (_v(6, 1, "500ml", 89_000, 0.43, 330, "HN-BXV"),),
        (1,),
        (58, 30, 9, 3),
        450,
        0.032,
        0.044,
        False,
        None,
        520,
    ),
)

#: Ad campaigns: id, title, the products they promote lives in ``Product.campaign``.
CAMPAIGNS: tuple[tuple[str, str], ...] = (
    ("9200000000001", "Hiên Nhà - Tối đa ROAS - Nhà bếp"),
    ("9200000000002", "Hiên Nhà - Tối đa ROAS - Dụng cụ"),
)
