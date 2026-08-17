"""城市等级映射（B-002 常模分组维度：一线/新一线/二线/其他）。

代码先行数据：迁移在 market_data 增加 city_tier 列后，以库内值为准；
本映射仅用于常模查询时推断用户意向城市等级（未覆盖城市默认「其他」）。
口径参考：第一财经·新一线城市研究所（2024 版）。
"""
CITY_TIERS: dict[str, str] = {
    # 一线
    "北京": "一线城市", "上海": "一线城市", "广州": "一线城市", "深圳": "一线城市",
    # 新一线
    "成都": "新一线城市", "杭州": "新一线城市", "重庆": "新一线城市", "武汉": "新一线城市",
    "西安": "新一线城市", "苏州": "新一线城市", "天津": "新一线城市", "南京": "新一线城市",
    "长沙": "新一线城市", "郑州": "新一线城市", "东莞": "新一线城市", "青岛": "新一线城市",
    "沈阳": "新一线城市", "宁波": "新一线城市", "昆明": "新一线城市",
    # 二线（常见）
    "合肥": "二线城市", "福州": "二线城市", "济南": "二线城市", "厦门": "二线城市",
    "大连": "二线城市", "无锡": "二线城市", "佛山": "二线城市", "哈尔滨": "二线城市",
    "石家庄": "二线城市", "南昌": "二线城市", "贵阳": "二线城市", "太原": "二线城市",
    "南宁": "二线城市", "珠海": "二线城市", "泉州": "二线城市", "兰州": "二线城市",
}

DEFAULT_TIER = "其他"


def resolve_city_tier(city: str | None) -> str:
    if not city:
        return DEFAULT_TIER
    return CITY_TIERS.get(city, DEFAULT_TIER)


def resolve_cities_tier(cities: list[str] | None) -> str:
    """多个意向城市取最高等级（一线 > 新一线 > 二线 > 其他）。"""
    if not cities:
        return DEFAULT_TIER
    order = ["一线城市", "新一线城市", "二线城市", "其他"]
    best = DEFAULT_TIER
    for city in cities:
        tier = resolve_city_tier(city)
        if order.index(tier) < order.index(best):
            best = tier
    return best
