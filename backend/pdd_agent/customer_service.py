"""Module 10 - FAQ 检索、供应商回复清洗、源链接改写和店内推荐。"""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

from .models import FaqEntry, ListingMapping

_URL_RE = re.compile(r"https?://[^\s<>\"'，。；）]+")
_CONTACT_RE = re.compile(
    r"(?:微信|V信|QQ|手机号|手机|电话|联系方式)\s*[：:]?\s*[A-Za-z0-9_-]{5,}|(?<!\d)1\d{10}(?!\d)",
    re.IGNORECASE,
)


def _terms(text: str) -> set[str]:
    return {term.lower() for term in re.findall(r"[A-Za-z0-9_\u4e00-\u9fff]+", text) if term}


def search_catalog(query: str, catalog: list[ListingMapping], limit: int = 3) -> list[ListingMapping]:
    """复用商品的标题/类目/标签做轻量检索，不额外引入向量库。"""
    query_terms = _terms(query)
    scored = []
    for listing in catalog:
        if listing.status != "PUBLISHED":
            continue
        haystack = " ".join((listing.title, listing.category, *listing.tags)).lower()
        score = sum(term in haystack for term in query_terms)
        if score:
            scored.append((score, listing))
    return [listing for _, listing in sorted(scored, key=lambda item: item[0], reverse=True)[:limit]]


def find_faq_answer(question: str, faqs: list[FaqEntry]) -> str | None:
    question_terms = _terms(question)
    matches = []
    for faq in faqs:
        terms = _terms(faq.question) | {keyword.lower() for keyword in faq.keywords}
        score = len(question_terms & terms)
        if score:
            matches.append((score, faq.answer))
    return max(matches, default=(0, None), key=lambda item: item[0])[1]


def record_faq(question: str, answer: str, faqs: list[FaqEntry]) -> FaqEntry:
    existing = next((faq for faq in faqs if faq.question.strip() == question.strip()), None)
    if existing:
        existing.answer = answer
        return existing
    faq = FaqEntry(question=question.strip(), answer=answer.strip())
    faqs.append(faq)
    return faq


def _goods_id(url: str) -> str:
    return parse_qs(urlparse(url).query).get("goods_id", [""])[0]


def sanitize_supplier_reply(
    reply: str,
    mappings: list[ListingMapping],
    *,
    customer_question: str = "",
    supplier_names: tuple[str, ...] = (),
) -> str:
    """清除联系方式/源店名；已映射链接改写，未映射链接删除并用店内相关商品替代。"""
    by_goods_id = {item.source_goods_id: item for item in mappings if item.source_goods_id}
    by_url = {item.source_url: item for item in mappings if item.source_url}
    unmapped = False

    def replace_url(match: re.Match[str]) -> str:
        nonlocal unmapped
        url = match.group(0).rstrip("，。；;）)")
        suffix = match.group(0)[len(url) :]
        listing = by_url.get(url) or by_goods_id.get(_goods_id(url))
        if listing and listing.status == "PUBLISHED":
            return listing.my_listing_url + suffix
        unmapped = True
        return suffix

    cleaned = _URL_RE.sub(replace_url, reply)
    cleaned = _CONTACT_RE.sub("", cleaned)
    for name in supplier_names:
        cleaned = cleaned.replace(name, "")
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"\s+([，。；;])", r"\1", cleaned).strip(" ，。；;\n")

    if unmapped:
        recommendations = search_catalog(customer_question or cleaned, mappings, limit=1)
        if recommendations:
            item = recommendations[0]
            cleaned = f"{cleaned}。你也可以看看：{item.title} {item.my_listing_url}".strip("。")
    return cleaned
