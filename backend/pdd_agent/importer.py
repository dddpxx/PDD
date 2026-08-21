"""Module 01 - Source Importer.

拼多多没有面向普通开发者的"商品详情查询"官方API（开放平台的商品接口是商家侧，管理自己店铺的商品，不能查询别人店铺的商品详情），
所以这里只能走"抓公开的商品详情页"这条路。DM.md §10.2 已经指出这块历史上高star的开源方案（pddSpider等）都因为反爬升级而失效，
所以本模块必须假设：抓取逻辑会随时因为页面改版/反爬策略而失效，不能把它当成稳定的基础设施来设计上层模块。

实现思路：
1. 如果传入的是短链接（分享链接），先跟随重定向拿到真实地址。
2. 从最终 URL 的 query string 里取 goods_id。
3. 用移动端 UA 请求页面 HTML，尝试从内嵌的 <script> JSON（常见于此类页面的 window.xxx = {...}）里解析出商品数据。
4. 解析失败时不静默返回假数据，而是抛出 ImportError 并保留原始 HTML 供人工排查——错误的商品数据比"卡住"更危险，
   因为它会一路带着错误信息流入AI生成和发布环节。
"""

from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse

import requests

from .models import ProductData, ProductImage, ProductSku, SpecValue

MOBILE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9",
}

# 不同页面版本可能用不同的全局变量名承载初始数据，按顺序尝试
_STATE_VAR_MARKERS = [
    "window.rawData=",
    "window.__INITIAL_STATE__=",
    "window.INIT_DATA=",
]


class ImportError_(Exception):
    """避免和内置 ImportError 撞名，仅本模块内部使用。"""


def resolve_goods_id(url: str, cookies: dict[str, str] | None = None) -> tuple[str, str]:
    """返回 (最终URL, goods_id)。短链接会先发一次请求跟随重定向。"""
    parsed = urlparse(url)
    goods_id = parse_qs(parsed.query).get("goods_id", [None])[0]
    if goods_id:
        return url, goods_id

    resp = requests.get(url, headers=MOBILE_HEADERS, cookies=cookies, timeout=15, allow_redirects=True)
    final_url = resp.url
    parsed = urlparse(final_url)
    goods_id = parse_qs(parsed.query).get("goods_id", [None])[0]
    if not goods_id:
        raise ImportError_(
            f"无法从链接里解析出 goods_id，最终跳转地址是: {final_url}。"
            "可能是链接格式变了，需要人工确认一下这个链接长什么样。"
        )
    return final_url, goods_id


def fetch_raw_page(url: str, cookies: dict[str, str] | None = None) -> str:
    resp = requests.get(url, headers=MOBILE_HEADERS, cookies=cookies, timeout=15)
    resp.raise_for_status()
    return resp.text


def _extract_balanced_json(html: str, marker: str) -> dict | None:
    """从 `marker` 后面的第一个 `{` 开始，按引号内转义规则数括号配对，找到真正的结束位置。

    之前用非贪婪正则 `\\{.*?\\};` 找结束位置，在真实页面（一段64KB的压缩JS+JSON混合内容）上
    会命中中间某个提前出现的 "};" 直接截断，拿到的只是完整对象的一小部分——这个问题是拿真实链接
    跑出来的，不是假设，所以换成正经的括号匹配而不是继续叠正则。
    """
    start = html.find(marker)
    if start == -1:
        return None
    brace_start = html.find("{", start)
    if brace_start == -1:
        return None

    depth = 0
    in_string = False
    escape = False
    for i in range(brace_start, len(html)):
        ch = html[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(html[brace_start : i + 1])
                except json.JSONDecodeError:
                    return None
    return None


def extract_state_json(html: str) -> dict | None:
    for marker in _STATE_VAR_MARKERS:
        data = _extract_balanced_json(html, marker)
        if data is not None:
            return data
    return None


def _looks_login_gated(state: dict) -> bool:
    store = state.get("store")
    if not isinstance(store, dict):
        return False
    init_data = store.get("initDataObj")
    return isinstance(init_data, dict) and init_data.get("needLogin") is True


def parse_product(state: dict, source_url: str, goods_id: str) -> ProductData:
    """把内嵌JSON映射成统一的 ProductData。

    字段路径是 2026-08-12 拿一个带登录态的真实响应核对过的真实路径，不是猜的：
    商品数据在 state["store"]["initDataObj"]["goods"]，价格类字段已经是"元"不是"分"
    （比如 minGroupPrice=15.74 就是 15.74元），只有 xxxInCent 后缀的字段才是分。
    """
    try:
        init_data = state["store"]["initDataObj"]
        goods = init_data["goods"]
    except (KeyError, TypeError) as e:
        raise ImportError_(
            f"没找到 state.store.initDataObj.goods，页面结构可能又变了（缺失的键：{e}）。"
        ) from e

    title = goods.get("goodsName") or ""
    price = float(goods.get("minOnSaleGroupPrice") or goods.get("minGroupPrice") or 0)

    # topGallery 是顶部轮播主图，detailGallery 是往下滚动的图文详情图——两个是不同的图片集合，
    # 之前只取了topGallery，detailGallery的图片URL只是拼进了raw_detail_text这个文本字段里，
    # 从没被当成"图片"进过product.images，Module 02/05挑参考图/挑KEEP图时根本看不到这些图。
    # detailGallery里经常混着topGallery没有的干净产品图（面料特写、尺码表、平铺图），也可能
    # 还是模特图（不同商家详情页风格不一样，不能假设一定是干净图），两个来源的图统一交给
    # Module 02 的分类器去判断，不在这里预设结论。
    top_gallery = goods.get("topGallery") or []
    detail_gallery_imgs = goods.get("detailGallery") or []
    seen_urls: set[str] = set()
    images: list[ProductImage] = []
    for img in top_gallery + detail_gallery_imgs:
        if not isinstance(img, dict):
            continue
        url = img.get("url", "")
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        images.append(ProductImage(url=url))

    raw_skus = goods.get("skus") or []
    skus = [
        ProductSku(
            sku_id=str(s.get("skuId") or ""),
            spec=" / ".join(sv.get("spec_value", "") for sv in s.get("specs", []) if sv.get("spec_value")),
            price=float(s.get("groupPrice") or 0),
            stock=int(s.get("quantity") or 0),
            # 2026-08-14新增：之前只存了拼接后的展示字符串，发布到自己店铺时需要把"颜色分类"和"尺码"
            # 分开填两个不同的表单区域，所以要保留每个维度原始的spec_key/spec_value，不能只有拼好的字符串。
            specs=[
                SpecValue(spec_key=sv.get("spec_key", ""), spec_value=sv.get("spec_value", ""))
                for sv in s.get("specs", [])
                if sv.get("spec_value")
            ],
            thumb_url=s.get("thumbUrl", ""),
        )
        for s in raw_skus
    ]

    detail_gallery = goods.get("detailGallery") or []
    detail_text = "\n".join(img.get("url", "") for img in detail_gallery if isinstance(img, dict))

    mall = init_data.get("mall") or {}

    return ProductData(
        source_platform="pdd",
        source_goods_id=goods_id,
        source_url=source_url,
        title=title,
        # 只有 catID/catID1~4 这种数字类目ID，没有可读的类目名字段，先留空，
        # 后面要加类目名要么接一个"类目ID->名称"的映射表，要么用 Module 02 从标题/图片里推断。
        category="",
        price=price,
        images=images,
        skus=skus,
        raw_detail_text=detail_text,
        supplier_shop_id=str(mall.get("mallId") or ""),
        supplier_shop_name=mall.get("mallName") or "",
    )


def import_product(url: str, cookies: dict[str, str] | None = None) -> ProductData:
    final_url, goods_id = resolve_goods_id(url, cookies=cookies)
    html = fetch_raw_page(final_url, cookies=cookies)
    state = extract_state_json(html)

    if state is None:
        dump_path = f"output/debug_raw_page_{goods_id}.html"
        with open(dump_path, "w", encoding="utf-8") as f:
            f.write(html)
        raise ImportError_(
            "页面里没找到已知的内嵌数据变量名，抓取逻辑大概率需要针对真实页面结构调整。"
            f"原始HTML已经存到 {dump_path}，可以打开看看数据实际藏在哪个 <script> 标签里。"
        )

    if _looks_login_gated(state):
        dump_path = f"output/debug_state_{goods_id}.json"
        with open(dump_path, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        raise ImportError_(
            "这个链接未登录状态下拿到的是登录门槛页（state.store.initDataObj.needLogin=true），"
            "商品数据（标题/价格/图片/SKU）不在这份未登录响应里，不是字段路径写错了。"
            f"未登录状态下的完整state已经存到 {dump_path}，可以确认里面确实没有商品字段。"
            "运行一次 `python login_pdd.py` 人工登录一遍拼多多移动端网页，存好登录态后，"
            "run_pipeline.py 会自动带上这份 Cookie 重新请求。"
        )

    product = parse_product(state, final_url, goods_id)

    if not product.title and not product.images and not product.skus:
        dump_path = f"output/debug_state_{goods_id}.json"
        with open(dump_path, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        raise ImportError_(
            "state里确实拿到了数据，但按现在猜的字段路径（goods_name/gallery/skus等）一个都没取到值，"
            "说明这个页面版本的真实字段名和猜测的不一样，不是没数据。"
            f"完整state已经存到 {dump_path}，对着它把 parse_product() 里的取值路径改成真实字段名。"
        )

    return product
