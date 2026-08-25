from __future__ import annotations

import json
import os
from dataclasses import asdict

from . import analyzer, copywriter, creative, detail_builder, importer, keywords
from .auth import load_cookies_for_requests
from .config import Settings
from .models import DetailPagePreview
from .store_publisher import build_publish_plan

DEFAULT_LOGIN_STATE_PATH = "pdd_login_state.json"


def run_pipeline(url: str, settings: Settings) -> DetailPagePreview:
    cookies = None
    state_path = os.environ.get("PDD_LOGIN_STATE_PATH", DEFAULT_LOGIN_STATE_PATH)
    if os.path.exists(state_path):
        cookies = load_cookies_for_requests(state_path)
        print(f"[0/6] 已加载登录态: {state_path}（{len(cookies)}个cookie）")
    else:
        print(f"[0/6] 没找到登录态文件 {state_path}，先按未登录状态试；不行就跑 `python login_pdd.py` 登录一次")

    print(f"[1/6] 导入商品: {url}")
    product = importer.import_product(url, cookies=cookies)
    print(f"      -> {product.title} | 价格 {product.price} | {len(product.images)}张图 | {len(product.skus)}个SKU")

    output_dir = os.path.join(settings.output_dir, product.source_goods_id)
    os.makedirs(output_dir, exist_ok=True)

    print("[2/6] 分析商品 + 图片分类")
    analysis = analyzer.analyze_product(product, settings)
    analyzer.classify_images(product, settings)
    kept = sum(1 for i in product.images if i.tag == "KEEP")
    print(f"      -> facts={analysis.facts} | KEEP图 {kept}/{len(product.images)} | 推荐场景 {analysis.recommended_scenes}")

    print("[3/6] 生成候选关键词")
    kw = keywords.generate_keywords(product, analysis, settings)
    print(f"      -> {len(kw)} 个候选关键词（主观打分，非真实热度统计）")

    print("[4/6] 生成文案")
    copy = copywriter.generate_copy(analysis, kw, settings)
    print(f"      -> 新标题: {copy.title}")

    print("[5/6] 生成AI场景图")
    generated_images = creative.generate_scene_images(product, analysis, settings, output_dir)
    print(f"      -> 生成了 {len(generated_images)} 张场景图")

    print("[6/6] 组装详情页预览")
    preview = detail_builder.build_detail_page(product, copy, kw, generated_images, output_dir)
    print(f"      -> 预览已生成: {os.path.join(output_dir, 'preview.html')}")

    draft_path = os.path.join(output_dir, "publish_draft.json")
    with open(draft_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "title": copy.title,
                "carousel_images": preview.carousel_images,
                "plan": asdict(build_publish_plan(product)),
            },
            f,
            ensure_ascii=False,
            indent=2,
        )
    print(f"      -> 发布草稿数据: {draft_path}")

    return preview
