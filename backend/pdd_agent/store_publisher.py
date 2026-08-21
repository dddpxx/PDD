"""Module 07 - Store Publisher。

2026-08-14路线转向：申请拼多多开放平台账号的门槛比预想高很多（域名ICP备案+软件著作权登记+演示视频，
见DM.md §14），用户当场决定放弃这条路，改成跟D1.2买家账号一样的思路——用Playwright操作商家后台
网页（mms.pinduoduo.com），不再走 pdd.goods.add 这类开放平台API。旧版本（调用pdd_client.call()
硬拼请求参数）已经跟不上实际方案，删掉了，pdd_client.py本身先留着，如果以后真申请到了开放平台
账号再捡回来用。

这个文件先只管"算清楚要往表单里填什么"（PublishPlan），不碰浏览器——具体怎么把这些值真正填进
真实网页表单，是另一个浏览器自动化模块的事（还没写），业务逻辑和UI操作分开，方便独立测试，
不用每次改一个数字都要真开一次浏览器跑一遍。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .models import ProductData, ProductSku

# 尺码要用拼多多"中国码"官方通用模板（表单尺码那栏本来就是勾选S/M/L/XL/2XL...这种标准码，
# 不接受自由文本），原商品的尺码文案是"L (100-120斤)"这种自定义写法，得从里面把标准码提出来。
_STANDARD_SIZE_PATTERN = re.compile(r"^([2-6]?X{0,3}[SLM]|XS|XXS)", re.IGNORECASE)


def _extract_standard_size(raw_size: str) -> str:
    """从"L (100-120斤)"这种原始尺码文案里提取出标准"中国码"（L/XL/2XL...），提不出来就原样返回，
    留给人工审核时发现、手动改，不是这里能兜底解决的。"""
    match = _STANDARD_SIZE_PATTERN.match(raw_size.strip())
    return match.group(1).upper() if match else raw_size


@dataclass
class PublishColorOption:
    name: str
    thumb_url: str  # 颜色分类每个选项要配的规格图，直接复用原商品对应SKU的缩略图


@dataclass
class PublishPlan:
    attributes: dict[str, str]
    colors: list[PublishColorOption]  # "颜色分类"要逐个添加的选项
    sizes: list[str]  # "尺码"要在"中国码"标准模板里勾选的规格值
    # 2026-08-14按反馈改成"批量设置"的填法——表单"价格及库存"区域本身就有一行
    # "全部颜色分类+全部尺码+库存+拼单价+单买价+批量设置按钮"，不用给65个SKU组合逐行填数字，
    # 选"全部颜色分类"+"全部尺码"，填一次这三个数字，点一次批量设置，所有组合就都套用上了。
    stock: int
    group_price: float
    single_price: float
    reference_price: float
    bulk_discount_quantity: int
    bulk_discount_rate: float
    shipping_promise: str
    no_reason_return: bool


# 2026-08-14按用户明确要求定的规则，都是针对这一次"男士内裤"商品的具体决定，
# 不是通用规律——换商品、换类目大概率要跟着重新定，不能想当然复用。
_PRICE_MARKUP = 5.0  # 拼单价 = 原商品拼单价 + 5元；单买价用户原话也是同一个数，两者相同
_REFERENCE_PRICE_MARKUP = 10.0  # 商品参考价 = 单买价 + 10元（表单要求参考价要大于最大单买价）
_BULK_DISCOUNT_QUANTITY = 2
_BULK_DISCOUNT_RATE = 0.95

# 商品属性：只填标"重要"的必填项，取值是用户直接给的，不是AI猜的或者从facts推断的。
# "成分含量"这个字段之前探索表单时没发现——大概率是选完"面料俗称=棉"之后才联动出现的子字段，
# 没走到那一步不会显现，用户是在真实表单里看到的，照抄进来。
_FIXED_ATTRIBUTES: dict[str, str] = {
    "面料俗称": "棉",
    "功能": "无痕",
    "腰型": "低腰",  # 2026-08-15由"中腰"改成"低腰"
    "裆部材质": "棉",
    "风格": "简约",  # "风格"这一项用户口述改成了"性格"，跟真实下拉框选项对不上，先按原值留着，等确认了具体文字再改
    "成分含量": "91%（含）—95%（含）",  # 用户直接看真实页面纠正的：中间是"—"破折号，不是"-"连字符，且"含"跟在每个百分比后面
    "服装款式细节": "U凸设计",  # 2026-08-15新增
    "适用年龄": "青年（18-25周岁）",  # 2026-08-15新增
    "工艺": "车缝",  # 2026-08-15新增
}


def _find_spec_value(sku: ProductSku, key_contains: str) -> str:
    for sv in sku.specs:
        if key_contains in sv.spec_key:
            return sv.spec_value
    return ""


def build_publish_plan(product: ProductData) -> PublishPlan:
    """把原商品的SKU数据 + 用户定的定价/属性规则，算成一份可以直接拿去填表单的方案。"""
    colors: dict[str, str] = {}  # name -> thumb_url，用dict顺便去重
    sizes: dict[str, None] = {}  # 只是当有序集合用，Python 3.7+ dict保证插入顺序
    for s in product.skus:
        color_name = _find_spec_value(s, "颜色") or _find_spec_value(s, "色")
        raw_size = _find_spec_value(s, "尺码") or _find_spec_value(s, "尺寸")
        if color_name and color_name not in colors:
            colors[color_name] = s.thumb_url
        if raw_size:
            sizes[_extract_standard_size(raw_size)] = None

    # 库存用原商品所有SKU里的最小值，保守一点——批量设置只能填一个统一数字，
    # 用户明确说"库存按原商品来"，但原商品每个SKU库存不完全一样（比如999/998这种小波动），
    # 取最小值不会让批量设置后的库存超过原商品实际能供应的量。
    stock_values = [s.stock for s in product.skus if s.stock > 0]
    stock = min(stock_values) if stock_values else 0

    # 原商品拼单价：实测这批SKU价格是统一的，取第一个SKU的价格作为"原产品拼单价"这个基准值。
    base_group_price = product.skus[0].price if product.skus else product.price
    price = round(base_group_price + _PRICE_MARKUP, 2)
    reference_price = round(price + _REFERENCE_PRICE_MARKUP, 2)

    return PublishPlan(
        attributes=dict(_FIXED_ATTRIBUTES),
        colors=[PublishColorOption(name=name, thumb_url=url) for name, url in colors.items()],
        sizes=list(sizes.keys()),
        stock=stock,
        group_price=price,
        single_price=price,
        reference_price=reference_price,
        bulk_discount_quantity=_BULK_DISCOUNT_QUANTITY,
        bulk_discount_rate=_BULK_DISCOUNT_RATE,
        shipping_promise="48小时",
        no_reason_return=False,
    )
