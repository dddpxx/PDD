"""Module 02 - Product Analyzer.

对应 DM.md §3.3 的"事实锁"原则：这里产出的 Facts 是后面 Module 04 文案生成能引用的唯一事实来源，
所以 prompt 里反复强调"看不到/不确定就不要写"，宁可 facts 少，也不能编。
"""

from __future__ import annotations

import json

from .config import Settings
from .llm_client import call_with_backoff, text_client
from .models import Facts, ProductAnalysis, ProductData
from .typo_fix import fix_known_typos_in_text

_ANALYZE_SYSTEM_PROMPT = """你是电商选品分析师。只根据用户提供的商品标题、类目、SKU信息和商品图片来分析，
严禁编造图片里没有出现、标题里没有提到的任何属性（比如"抗菌""德国科技"这类未经证实的卖点绝对不能写）。
不确定的字段就留空数组或空字符串，不要猜。
只输出JSON，不要输出多余文字。JSON结构：
{
  "facts": {"material": "", "style": "", "gender": "", "season": "", "features": []},
  "category_refined": "",
  "target_audience": "",
  "selling_points": [],
  "recommended_scenes": []
}
facts.gender 只能填"男"、"女"、"通用"三选一，或者商品本身没有性别指向就留空字符串——不要写"男士""女款"这种带修饰的自由文本，
后面 Module 05 生成模特图时是按这个字段做精确匹配来选模特人设的，写成自由文本会导致匹配不上、模特图直接生成不出来。
recommended_scenes 是给后面AI生成场景图用的，比如男士内裤类目可以给"健身房""更衣室""晨间居家"这种具体场景，
数量给3-5个，必须和商品类目/人群匹配，不要给无关场景。"""


def analyze_product(product: ProductData, settings: Settings) -> ProductAnalysis:
    client = text_client(settings)

    content: list[dict] = [
        {
            "type": "text",
            "text": (
                f"标题：{product.title}\n"
                f"类目：{product.category}\n"
                f"SKU：{[s.spec for s in product.skus]}\n"
                "以下是商品图片，请结合图片里能看到/读到的信息一起分析："
            ),
        }
    ]
    for img in product.images[:6]:
        content.append({"type": "image_url", "image_url": {"url": img.url}})

    resp = call_with_backoff(
        lambda: client.chat.completions.create(
            model=settings.text_model,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": _ANALYZE_SYSTEM_PROMPT},
                {"role": "user", "content": content},
            ],
        )
    )
    data = json.loads(resp.choices[0].message.content)
    facts_data = data.get("facts", {})
    # 图片上的错字不只会留在图片本身里——这一步读图提取facts时会把叠加文字原样抄进features，
    # 实测出现过把"不勒退"这个错字当成正经产品特性抄进facts.features的情况，Module 04写文案时
    # 又会引用facts，错字就这样传下去了。这里用同一张已知错字表对文本字段做一次兜底替换。
    if "features" in facts_data:
        facts_data["features"] = [fix_known_typos_in_text(f) for f in facts_data["features"]]
    facts = Facts(**facts_data)
    selling_points = [fix_known_typos_in_text(s) for s in data.get("selling_points", [])]
    return ProductAnalysis(
        facts=facts,
        category_refined=data.get("category_refined", product.category),
        target_audience=data.get("target_audience", ""),
        selling_points=selling_points,
        recommended_scenes=data.get("recommended_scenes", []),
    )


_CLASSIFY_SYSTEM_PROMPT = """你是电商图片审核员。给你一组商品图片的URL（按顺序编号），给每一张图输出判断。

判断优先级：先看画面里有没有真人模特（人体/躯干/皮肤，哪怕只露出一部分身体、没有露脸）在展示/穿着这件商品——
只要有真人出镜，不管画面上还叠加没叠加文字说明，一律归"model"。只有确认画面里完全没有真人身体出现，
才继续按下面的规则细分：

1. type: "product"(产品本体：平铺/细节/面料/尺码表/包装，没有任何叠加文字或图形标注，画面里没有真人)
   | "model"(真人模特图——画面里有真人模特的身体在展示/穿着这件商品，哪怕同时叠加了文字说明，也优先归这一类，不能因为文字显眼就误判成text_info)
   | "scene"(生活场景图，没有真人模特但有场景布置，商品本身可能拍得不够清楚)
   | "text_info"(以叠加文字/图形说明为主的信息图，比如面料卖点拼图、四宫格细节拼版、参数说明图——前提是画面里没有真人身体，
     只要产品本身在画面里清晰可见，即使叠加了文字说明也算这一类)

2. tag: type是"product"或"text_info"给"KEEP"（这两类都可以直接用进详情页，文字说明类图片不需要因为有文字就丢弃）；
   type是"model"或"scene"给"DROP"（不用原店的模特出镜图和生活场景图——目的是让顾客理解详情页里的人物图都是我们自己店铺拍的，
   不是从原商品那边搬来的模特图，这个界限只针对"有没有真人模特出镜"，不针对"有没有文字"，文字再多、只要露了真人身体就必须DROP）。

只输出JSON：{"results": [{"index": 0, "type": "", "tag": ""}, ...]}，index和输入编号一一对应。"""


def classify_images(product: ProductData, settings: Settings) -> None:
    if not product.images:
        return
    client = text_client(settings)

    content: list[dict] = [{"type": "text", "text": "请给下面这些图片分类："}]
    for i, img in enumerate(product.images):
        content.append({"type": "text", "text": f"[{i}]"})
        content.append({"type": "image_url", "image_url": {"url": img.url}})

    resp = call_with_backoff(
        lambda: client.chat.completions.create(
            model=settings.text_model,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": _CLASSIFY_SYSTEM_PROMPT},
                {"role": "user", "content": content},
            ],
        )
    )
    data = json.loads(resp.choices[0].message.content)
    by_index = {r["index"]: r for r in data.get("results", [])}
    seen_urls: set[str] = set()
    for i, img in enumerate(product.images):
        result = by_index.get(i)
        if result:
            img.type = result.get("type", "unknown")
            img.tag = result.get("tag", "DROP")
        # 2026-08-13 按反馈调整：只按"有没有真人模特出镜"来DROP，不是"有没有叠加文字"——
        # 带文字说明的图（细节特写、四宫格图文介绍等）本来就可以用，只是要挑出真人模特图去掉，
        # 让详情页里出现的人物图只有我们自己生成的场景图，不是从原商品那边搬来的模特图。
        if img.type not in ("product", "text_info"):
            img.tag = "DROP"
        # 同一个商品的图片列表里偶尔会出现完全相同的URL（拼多多接口本身返回的重复项，不是我们的bug），
        # 保留原图时如果不去重，会导致详情页里出现两张一模一样的图，占了位置又没有信息增量。
        if img.url in seen_urls:
            img.tag = "DROP"
        seen_urls.add(img.url)
