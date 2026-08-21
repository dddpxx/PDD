"""Module 04 - Copywriter AI。对应 DM.md §3.3 事实锁 + §3.4 关键词来自统计。"""

from __future__ import annotations

import json

from .config import Settings
from .llm_client import call_with_backoff, text_client
from .models import Copy, Keyword, ProductAnalysis
from .typo_fix import fix_known_typos_in_text

_SYSTEM_PROMPT = """你是电商文案撰写员，必须严格遵守"事实锁"：只能使用用户提供的facts和selling_points里已经出现的信息，
禁止添加任何未经确认的功效/材质/认证类描述（比如平台/机构认证、"医用级""德国技术"这类没有来源的词，绝对不能写）。
关键词列表是候选参考，只能挑选和facts不矛盾的词用进标题，relevance分数高的优先考虑，但事实优先于关键词热度。
输出JSON：{"title": "", "bullet_points": ["", "", ""], "description": ""}
title控制在30字以内，符合国内电商标题习惯（关键词堆叠但通顺，不是营销口号）。
bullet_points是3-5条卖点短句，每条都必须是直接对顾客说的产品卖点本身（比如"双C囊袋设计，透气更清爽"），
禁止写"标题和图片均有体现""该卖点已在详情图展示"这类自我描述/元描述句子——顾客看不到你的生成过程，
这种句子写出来毫无意义，只会显得很怪。
description是200-400字的详情文案，语气克制，不要浮夸营销词，必须分成2-3个自然段，每段聚焦一个角度
（比如材质工艺、穿着体验、适用场景），段落之间用一个空行（也就是两个换行符\\n\\n）隔开——
不要写成一整段不分段的大长句堆在一起，那样在详情页里读起来很挤。"""


def generate_copy(analysis: ProductAnalysis, keywords: list[Keyword], settings: Settings) -> Copy:
    client = text_client(settings)
    user_content = (
        f"facts：{json.dumps(analysis.facts.__dict__, ensure_ascii=False)}\n"
        f"selling_points：{analysis.selling_points}\n"
        f"target_audience：{analysis.target_audience}\n"
        f"候选关键词（term/relevance/note）：{[(k.term, k.relevance, k.note) for k in keywords]}"
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
    # 最后再兜底过一遍已知错字表——facts/selling_points里已经在Module 02那边清过一次了，
    # 但这里的title/description是LLM重新组织措辞生成的，理论上不该再引入错字，双重保险不多余。
    return Copy(
        title=fix_known_typos_in_text(data.get("title", "")),
        bullet_points=[fix_known_typos_in_text(b) for b in data.get("bullet_points", [])],
        description=fix_known_typos_in_text(data.get("description", "")),
    )
