"""Module 09 - Procurement Engine（起步阶段，只做不依赖拼多多开放平台账号、且相对低风险的部分）。

2026-08-13：这个模块从"跟Module07一样卡在缺开放平台账号"的空档期里先动起来，但真正"用买家账号
自动登录源店拍单支付"这一步，DM.md §10.2 调研早就确认过GitHub上没有任何成熟方案可抄，属于全新开发，
而且涉及真实资金和平台规则风险——这部分不适合我在没有用户在场盯着测试的情况下自己写完就直接跑，
所以这里先只做"利润守卫核价"和"买家账号池调度选择"这两块相对安全、可以独立验证的逻辑，
真正的下单执行(`place_order`)先留成明确的TODO，等到了要接入真实执行的阶段，需要用户在场一起测。
"""

from __future__ import annotations

import time

from . import importer
from .config import Settings
from .models import BuyerAccount, ProcurementTask, SkuMapping


def check_profit_guard(
    task: ProcurementTask,
    mapping: SkuMapping,
    settings: Settings,
    cookies: dict[str, str] | None = None,
    daily_spend_so_far: float = 0.0,
) -> ProcurementTask:
    """下单前重新核价（对应 DM.md §3.5 利润守卫）：重新抓一次源商品的当前价格/库存，
    不能用几天前抓到的旧价格算利润——源头随时可能涨价/降价/下架/缺货。

    复用 importer.import_product()（跟 Module 01 是同一套抓取逻辑），不用重新写一套抓取代码；
    这一步是只读操作（不下单、不花钱），可以随时安全地反复调用测试，不需要真的买家账号也能测
    （只要能拿到能读到商品数据的登录态cookies，跟Module01的cookies.txt是同一份）。
    """
    try:
        source_product = importer.import_product(mapping.source_url, cookies=cookies)
    except Exception as e:
        task.profit_guard_status = "NEEDS_HUMAN"
        task.expected_cost = 0.0
        print(f"      [利润守卫] 抓取源商品失败，转人工处理：{e}")
        return task

    matched_sku = next((s for s in source_product.skus if s.sku_id == mapping.source_sku_id), None)
    if matched_sku is None:
        task.profit_guard_status = "NEEDS_HUMAN"
        print(f"      [利润守卫] 源商品里找不到 sku_id={mapping.source_sku_id}，可能SKU已下架，转人工处理")
        return task

    if matched_sku.stock < task.quantity:
        task.profit_guard_status = "NEEDS_HUMAN"
        print(f"      [利润守卫] 源SKU库存不足（库存{matched_sku.stock} < 需求{task.quantity}），转人工处理")
        return task

    current_cost = matched_sku.price * task.quantity
    task.expected_cost = current_cost

    revenue = task.sale_price * task.quantity
    margin = revenue - current_cost
    margin_rate = margin / revenue if revenue > 0 else 0.0

    if daily_spend_so_far + current_cost > settings.procurement_daily_spend_cap:
        task.profit_guard_status = "NEEDS_HUMAN"
        print(
            f"      [利润守卫] 会超出每日采购总额上限"
            f"（已花{daily_spend_so_far:.2f}+本单{current_cost:.2f} > 上限{settings.procurement_daily_spend_cap}），转人工处理"
        )
        return task

    if margin_rate < settings.procurement_min_margin_rate or margin < settings.procurement_min_margin_absolute:
        task.profit_guard_status = "BLOCKED_LOW_MARGIN"
        print(
            f"      [利润守卫] 毛利不达标（毛利{margin:.2f}元/{margin_rate:.1%}，"
            f"要求 >={settings.procurement_min_margin_absolute}元 且 >={settings.procurement_min_margin_rate:.0%}），暂停采购"
        )
        return task

    task.profit_guard_status = "PASS"
    print(f"      [利润守卫] 通过，预计成本{current_cost:.2f}元，毛利{margin:.2f}元（{margin_rate:.1%}）")
    return task


def assign_batch(task: ProcurementTask, settings: Settings, now: float | None = None) -> ProcurementTask:
    """D1.1：每天以配置的cutoff小时为界，之前的订单当天处理，之后的顺延次日，不连夜赶单。"""
    now = now if now is not None else time.time()
    hour = time.localtime(now).tm_hour
    task.procurement_status = "QUEUED_TODAY" if hour < settings.procurement_cutoff_hour else "DEFERRED_NEXT_DAY"
    return task


def select_buyer_account(pool: list[BuyerAccount], now: float | None = None) -> BuyerAccount | None:
    """从账号池里选一个当前可用的账号（D1.1/D1.4）：账号状态正常、今天下单数没到上限、
    距离上次下单的间隔够长。找不到可用账号返回None，调用方应该转人工/排队等下一个可用时机，
    不能为了"总要选一个"就违反这几条限制——这几条限制本身就是D1里为了控制账号风控风险定的。
    """
    now = now if now is not None else time.time()
    candidates = [
        a
        for a in pool
        if a.status == "ACTIVE"
        and a.orders_today_count < a.daily_order_limit
        and (now - a.last_order_at) >= a.min_interval_seconds
    ]
    if not candidates:
        return None
    # 选距离上次下单时间最久的账号，尽量把下单机会平均分摊到整个账号池，不要老是用同一个账号
    return min(candidates, key=lambda a: a.last_order_at)


def place_order(task: ProcurementTask, mapping: SkuMapping, account: BuyerAccount) -> None:
    """真正用买家账号去源店下单、填客户收货信息、支付——这是整个项目里最核心也最没有先例可抄的一步
    （DM.md §10.2 调研结论：GitHub上没有任何成熟/可信的开源项目做这件事）。

    不在这里直接写实现：这一步涉及真实资金和平台规则风险，第一版必须由用户在场一起测试、
    亲眼看着流程走一遍确认没问题，不能我自己写完代码就说"应该能用"。等用户准备好要开始测这一步，
    我们一起从"只走到支付前一步、不真的提交支付"这种更保守的版本开始，逐步验证，不要一上来
    就是完全自动扣款的版本。
    """
    raise NotImplementedError(
        "买家账号下单执行还没有实现——这一步涉及真实资金和平台风控风险，需要用户在场一起测试再开始写，"
        "不是缺技术方案，是主动决定不在没人盯着的情况下自己写完就跑。"
    )
