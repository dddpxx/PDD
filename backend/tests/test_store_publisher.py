from pdd_agent import merchant_publisher
from pdd_agent.models import ProductData, ProductSku, SpecValue
from pdd_agent.store_publisher import build_publish_plan


def _plan():
    product = ProductData(
        source_platform="pdd",
        source_goods_id="G-1",
        source_url="https://example.test/G-1",
        title="test",
        category="内裤",
        price=10,
        skus=[
            ProductSku(
                "S-1",
                "黑色 / XL (120-140斤)",
                10,
                8,
                [SpecValue("颜色分类", "黑色"), SpecValue("尺码", "XL (120-140斤)")],
                "https://example.test/black.png",
            )
        ],
    )
    return build_publish_plan(product)


class _MissingVerification:
    def count(self):
        return 0

    def nth(self, _index):
        return self

    def is_visible(self):
        return False


class _Page:
    def __init__(self):
        self.waits = []

    def get_by_text(self, *_args, **_kwargs):
        return _MissingVerification()

    def wait_for_timeout(self, value):
        self.waits.append(value)


def test_publish_plan_extracts_variants_and_prices():
    plan = _plan()
    assert [color.name for color in plan.colors] == ["黑色"]
    assert plan.sizes == ["XL"]
    assert (plan.stock, plan.group_price, plan.single_price, plan.reference_price) == (8, 15, 15, 25)


def test_form_orchestration_retries_dynamic_attributes(monkeypatch):
    calls = []
    outcomes = iter([["成分含量"], []])
    monkeypatch.setattr(merchant_publisher, "fill_title", lambda *_: calls.append("title"))
    monkeypatch.setattr(merchant_publisher, "upload_carousel_images", lambda *_: calls.append("images"))
    monkeypatch.setattr(merchant_publisher, "fill_attributes", lambda *_: next(outcomes))
    monkeypatch.setattr(merchant_publisher, "fill_color_options", lambda *_: calls.append("colors"))
    monkeypatch.setattr(merchant_publisher, "select_sizes", lambda *_: calls.append("sizes"))
    monkeypatch.setattr(merchant_publisher, "fill_inventory_and_prices", lambda *_: calls.append("prices"))
    monkeypatch.setattr(merchant_publisher, "fill_shipping_and_services", lambda *_: calls.append("shipping"))

    failed = merchant_publisher.fill_publish_form(
        _Page(), title="title", carousel_images=["a.png"], plan=_plan()
    )

    assert failed == []
    assert calls == ["title", "images", "colors", "sizes", "prices", "shipping"]
