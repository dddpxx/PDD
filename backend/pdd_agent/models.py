from dataclasses import dataclass, field


@dataclass
class ProductImage:
    url: str
    local_path: str | None = None
    tag: str = "UNSET"  # KEEP | DROP | UNSET(待Module02打标)
    type: str = "unknown"  # product | model | scene | text_info | unknown


@dataclass
class SpecValue:
    spec_key: str  # 规格维度名，比如"颜色分类""尺码"
    spec_value: str  # 该维度的取值，比如"咖啡色""L (100-120斤)"


@dataclass
class ProductSku:
    sku_id: str
    spec: str  # 各维度拼接后的展示用字符串，比如"咖啡色 / L (100-120斤)"
    price: float
    stock: int
    specs: list[SpecValue] = field(default_factory=list)  # 保留每个维度单独的key/value，发布时要分开填颜色和尺码
    thumb_url: str = ""  # 该SKU（一般是颜色维度）的规格缩略图，发布时"颜色分类"那栏要复用这张图


@dataclass
class ProductData:
    source_platform: str
    source_goods_id: str
    source_url: str
    title: str
    category: str
    price: float
    images: list[ProductImage] = field(default_factory=list)
    skus: list[ProductSku] = field(default_factory=list)
    raw_detail_text: str = ""
    supplier_shop_id: str = ""
    supplier_shop_name: str = ""


@dataclass
class Facts:
    material: str = ""
    style: str = ""
    gender: str = ""
    season: str = ""
    features: list[str] = field(default_factory=list)


@dataclass
class ProductAnalysis:
    facts: Facts
    category_refined: str
    target_audience: str
    selling_points: list[str]
    recommended_scenes: list[str]


@dataclass
class Keyword:
    term: str
    relevance: int  # 0-100，当前版本由LLM主观打分，不是真实搜索热度统计（见README/DM §3.4）
    note: str = ""


@dataclass
class Copy:
    title: str
    bullet_points: list[str]
    description: str


@dataclass
class GeneratedImage:
    scene_name: str
    local_path: str
    prompt_used: str


@dataclass
class DetailPagePreview:
    goods_id: str
    copy: Copy
    ordered_images: list[str]  # 本地路径，AI图在前，KEEP原图在后
    keywords: list[Keyword]
    # 对应发布表单"基本信息"里的图片位。长图（辅助长图）在拼多多上是用于搜索/推荐流量场景的素材，
    # 不是详情页内容——2026-08-14一开始理解错了，以为把所有图拼一张长图就是详情页，已经改正：
    # 详情页内容实际靠"商品轮播图"（表单本身写了"若未编辑，轮播图将自动填充至图文详情"），
    # 所以把全部图片（AI图+graphics卡片+原图）都放进轮播图，不再单独生成长图。
    carousel_images: list[str] = field(default_factory=list)  # 商品轮播图：全部图片，上限10张
    white_bg_image: str = ""  # 商品辅助图-白底图：AI图里随便挑一张


# ---- Module 09 采购履约相关模型，对应 DM.md §4/§6 的设计 ----


@dataclass
class SkuMapping:
    """自己店铺的SKU 到 采购来源SKU 的映射，采购下单前靠这个找到该去哪个源商品拍哪个规格。

    source_url 必须存完整的原始分享链接（比如 goods2.html?ps=xxx 这种），不能只存 source_goods_id
    指望后面拼URL重新访问——2026-08-13实测过，光用 `goods.html?goods_id=X` 或 `goods1.html?goods_id=X`
    这种不带分享token的URL访问，拼多多服务端直接返回 `window.rawData=null`（页面结构在，但没有真实数据），
    必须是当初导入时那条完整的分享链接才能稳定拿到数据。分享链接里的 `ps` token会不会有时效性、
    多久后会失效，目前没有验证过，如果后面发现价格核实这一步突然大批失败，先往这个方向排查。"""

    my_sku_id: str
    source_platform: str
    source_goods_id: str
    source_sku_id: str
    source_url: str


@dataclass
class BuyerAccount:
    """采购买家账号池里的一个账号（D1）。登录态走 auth.py 那套"人工正常浏览器登录+cookie导出"，
    不是Playwright自动化登录——D1.2已经有实测教训，自动化登录会被拼多多风控拦截发验证码。"""

    account_id: str
    login_state_path: str  # cookies.txt 或 storage_state.json 路径，见 auth.load_cookies_for_requests
    status: str = "ACTIVE"  # ACTIVE | LOGIN_EXPIRED | SUSPENDED
    last_order_at: float = 0.0  # time.time()，用来算下一次下单是否满足 min_interval_seconds
    min_interval_seconds: int = 900  # D1.1：同账号不能背靠背下单，默认15分钟，随机区间后面再细化
    orders_today_count: int = 0
    daily_order_limit: int = 2  # D1.4：网上经验贴参考值，非官方数据，保守起步
    balance: float = 0.0
    low_balance_threshold: float = 50.0
    device_or_proxy_id: str = ""  # D1.4：账号尽量固定绑定同一设备/出口IP，避免多账号共用IP的关联风控


@dataclass
class ProcurementTask:
    """一次采购任务：客户在自己店铺下的一单，对应到要去源店拍的一次购买。"""

    order_id: str
    my_sku_id: str
    quantity: int
    customer_name: str
    customer_phone: str
    customer_address: str
    sale_price: float  # 客户在自己店铺付的钱（单价）
    created_at: float = 0.0
    expected_cost: float = 0.0  # 下单时预估的采购成本，供 Profit Guard 用
    profit_guard_status: str = "PENDING"  # PENDING | PASS | BLOCKED_LOW_MARGIN | NEEDS_HUMAN
    assigned_buyer_account_id: str = ""
    procurement_status: str = "PENDING"
    # PENDING | QUEUED_TODAY | DEFERRED_NEXT_DAY | AWAITING_HUMAN | PAID | SHIPPED | FAILED


# ---- Module 08 订单中心 ----


@dataclass
class OrderItem:
    my_sku_id: str
    quantity: int
    sale_price: float


@dataclass
class CustomerOrder:
    order_id: str
    customer_name: str
    customer_phone: str
    customer_address: str
    items: list[OrderItem]
    status: str = "PAID"
    created_at: float = 0.0


# ---- Module 10 客服 ----


@dataclass
class ListingMapping:
    source_goods_id: str
    source_url: str
    my_listing_id: str
    my_listing_url: str
    title: str = ""
    category: str = ""
    tags: list[str] = field(default_factory=list)
    status: str = "PUBLISHED"


@dataclass
class FaqEntry:
    question: str
    answer: str
    keywords: list[str] = field(default_factory=list)
