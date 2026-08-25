"""Module 08 - 把销售渠道订单标准化并生成 Module 09 采购任务。

渠道抓取/API 适配器只需把原始订单转换成这里定义的标准字典；本模块不猜拼多多商家后台
的私有字段，也不保存客户隐私。持久化、幂等和加密由生产接入层负责。
"""

from __future__ import annotations

from collections.abc import Iterable

from .config import Settings
from .models import CustomerOrder, OrderItem, ProcurementTask, SkuMapping
from .procurement import assign_batch


def parse_order(data: dict) -> CustomerOrder:
    """解析平台无关的标准订单字典，并在隐私数据进入采购链路前完成必要校验。"""
    required = ("order_id", "customer_name", "customer_phone", "customer_address", "items")
    missing = [key for key in required if not data.get(key)]
    if missing:
        raise ValueError(f"订单缺少必填字段: {', '.join(missing)}")

    items = [
        OrderItem(
            my_sku_id=str(item.get("my_sku_id", "")).strip(),
            quantity=int(item.get("quantity", 0)),
            sale_price=float(item.get("sale_price", 0)),
        )
        for item in data["items"]
    ]
    if not items or any(not item.my_sku_id or item.quantity <= 0 or item.sale_price <= 0 for item in items):
        raise ValueError("订单 items 必须包含有效的 my_sku_id、正数 quantity 和 sale_price")

    return CustomerOrder(
        order_id=str(data["order_id"]),
        customer_name=str(data["customer_name"]),
        customer_phone=str(data["customer_phone"]),
        customer_address=str(data["customer_address"]),
        items=items,
        status=str(data.get("status", "PAID")).upper(),
        created_at=float(data.get("created_at", 0)),
    )


def create_procurement_tasks(
    order: CustomerOrder,
    mappings: Iterable[SkuMapping],
    settings: Settings,
    *,
    now: float | None = None,
) -> list[ProcurementTask]:
    """仅已支付订单可进入采购队列；每个订单行生成一条可独立核价的采购任务。"""
    if order.status != "PAID":
        raise ValueError(f"订单 {order.order_id} 状态为 {order.status}，不能创建采购任务")

    by_sku = {mapping.my_sku_id: mapping for mapping in mappings}
    missing = [item.my_sku_id for item in order.items if item.my_sku_id not in by_sku]
    if missing:
        raise ValueError(f"订单 {order.order_id} 缺少 SKU 映射: {', '.join(missing)}")

    tasks = []
    for item in order.items:
        task = ProcurementTask(
            order_id=order.order_id,
            my_sku_id=item.my_sku_id,
            quantity=item.quantity,
            customer_name=order.customer_name,
            customer_phone=order.customer_phone,
            customer_address=order.customer_address,
            sale_price=item.sale_price,
            created_at=order.created_at,
        )
        tasks.append(assign_batch(task, settings, now=now))
    return tasks
