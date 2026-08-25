from pdd_agent.customer_service import find_faq_answer, sanitize_supplier_reply
from pdd_agent.models import FaqEntry, ListingMapping


def test_supplier_reply_is_sanitized_and_links_are_rewritten():
    catalog = [
        ListingMapping(
            source_goods_id="100",
            source_url="https://mobile.yangkeduo.com/goods.html?goods_id=100",
            my_listing_id="mine-100",
            my_listing_url="https://shop.example/mine-100",
            title="透气男士内裤",
            category="内裤",
            tags=["透气"],
        )
    ]
    reply = (
        "源店A说看 https://mobile.yangkeduo.com/goods.html?goods_id=100，"
        "另一个是 https://mobile.yangkeduo.com/goods.html?goods_id=999，微信 wx12345"
    )

    cleaned = sanitize_supplier_reply(
        reply,
        catalog,
        customer_question="透气 内裤",
        supplier_names=("源店A",),
    )

    assert "goods_id=100" not in cleaned
    assert "goods_id=999" not in cleaned
    assert "wx12345" not in cleaned
    assert "源店A" not in cleaned
    assert cleaned.count("https://shop.example/mine-100") == 2


def test_faq_answer_uses_keywords():
    faqs = [FaqEntry("这件商品怎么洗", "请使用冷水轻柔洗涤", ["清洗", "洗涤"])]
    assert find_faq_answer("清洗", faqs) == "请使用冷水轻柔洗涤"
    assert find_faq_answer("发货", faqs) is None
