"""Module 03 - Keyword Intelligence（V0，轻量版）。

DM.md §3.4 的要求是"关键词来自统计，不是AI臆测"——真正做法应该是抓同类目商品的标题/搜索结果做词频统计。
但那需要解决和 Module 01 同样的"拼多多搜索结果页抓取"问题，§10.2 调研已经确认这块没有现成方案，工作量不小。

这一版先做替代品：让LLM基于本商品的 facts/卖点/标题，给出候选关键词 + 一个1-100的"主观相关性"分数，
明确标注这不是真实搜索热度，只是候选池，用来先把 Module 04 的文案流程跑通。
等 Module 01 的抓取能力扩展到能抓同类目商品列表后，这里要换成真实词频统计。
"""

from __future__ import annotations

import json

from .config import Settings
from .llm_client import call_with_backoff, text_client
from .models import Keyword, ProductAnalysis, ProductData

_SYSTEM_PROMPT = """你是电商标题优化顾问。根据商品标题、类目和已确认的商品事实(facts)，
列出10-15个这个商品适合出现在标题/详情里的关键词候选，按你认为的相关性给1-100的分数。
只能基于给定的事实和常识给关键词，不要引入事实里没有的属性词。
只输出JSON：{"keywords": [{"term": "", "relevance": 0, "note": ""}, ...]}
note字段简要说明这个词为什么相关（比如"来自material字段"、"类目通用词"）。"""


def generate_keywords(product: ProductData, analysis: ProductAnalysis, settings: Settings) -> list[Keyword]:
    client = text_client(settings)
    user_content = (
        f"标题：{product.title}\n"
        f"类目：{analysis.category_refined}\n"
        f"facts：{json.dumps(analysis.facts.__dict__, ensure_ascii=False)}\n"
        f"卖点：{analysis.selling_points}"
    )
    resp = call_with_backoff(
        lambda: client.chat.completions.create(
            model=settings.text_model,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
        )
    )
    data = json.loads(resp.choices[0].message.content)
    return [
        Keyword(term=k["term"], relevance=int(k.get("relevance", 0)), note=k.get("note", ""))
        for k in data.get("keywords", [])
    ]
