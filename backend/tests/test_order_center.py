from types import SimpleNamespace

import pytest

from pdd_agent.models import SkuMapping
from pdd_agent.order_center import create_procurement_tasks, parse_order


def _order(status="PAID"):
    return parse_order(
        {
            "order_id": "O-1",
            "customer_name": "测试用户",
            "customer_phone": "13800000000",
            "customer_address": "测试地址",
            "status": status,
            "items": [{"my_sku_id": "M-1", "quantity": 2, "sale_price": 29.9}],
        }
    )


def test_paid_order_creates_procurement_task():
    mapping = SkuMapping("M-1", "pdd", "G-1", "S-1", "https://example.test/G-1")
    tasks = create_procurement_tasks(
        _order(),
        [mapping],
        SimpleNamespace(procurement_cutoff_hour=24),
        now=0,
    )

    assert [(task.my_sku_id, task.quantity, task.procurement_status) for task in tasks] == [
        ("M-1", 2, "QUEUED_TODAY")
    ]


def test_unpaid_or_unmapped_order_is_rejected():
    settings = SimpleNamespace(procurement_cutoff_hour=24)
    with pytest.raises(ValueError, match="不能创建采购任务"):
        create_procurement_tasks(_order("CANCELLED"), [], settings)
    with pytest.raises(ValueError, match="缺少 SKU 映射"):
        create_procurement_tasks(_order(), [], settings)
