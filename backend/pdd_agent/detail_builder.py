"""Module 06 - Detail Builder。

对应 DM.md §3.1"不做一键全自动发布，必须人工审核"：产出两样东西，用途不一样——
1. preview.html：原商品 vs 改款商品左右对比，给人工审核用的，审核完不会拿去发布。
2. detail_page.html + ordered_images 这一串图片文件：模拟真实手机端商品详情页从上到下的滚动效果，
   这才是以后 Module 07 发布时真正会传给拼多多的那组详情图，图片顺序、内容都是"发布件"本身。

详情页的图片顺序按 DM.md §8 的设计：AI场景图 → AI卖点图/产品信息图 → 允许保留的原商品产品图。
卖点图/产品信息图不是让AI画图生成的（AI画文字经常乱码变形，商品logo那次已经踩过），
是用 Pillow 直接把 Copy 里的文字画成图（见 detail_graphics.py），保证文字100%可读。
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict

from . import detail_graphics
from .models import Copy, DetailPagePreview, GeneratedImage, Keyword, ProductData
from .utils import download_file


def build_detail_page(
    product: ProductData,
    copy: Copy,
    keywords: list[Keyword],
    generated_images: list[GeneratedImage],
    output_dir: str,
) -> DetailPagePreview:
    kept_dir = os.path.join(output_dir, "kept")
    # type in (product, text_info) 是双保险：analyzer.py 已经在代码里按同样的规则打了tag，
    # 这里再查一遍type，防止以后谁改了analyzer的逻辑又把model类型的图漏进最终详情页。
    # text_info（带文字说明的细节图/四宫格图文介绍）是允许保留的，只排除model（真人模特出镜图）。
    kept_images = [img for img in product.images if img.tag == "KEEP" and img.type in ("product", "text_info")]
    kept_paths = []
    for i, img in enumerate(kept_images):
        path = download_file(img.url, os.path.join(kept_dir, f"kept_{i}.jpg"))
        # 2026-08-13：原图错别字的自动涂改机制（OCR+圆角矩形补丁）已经按用户反馈取消——
        # 生成效果视觉上不自然（"太难受了"），用户表示这种细节自己手动处理，不需要程序自动改。
        # 原图里如果带了错别字，就原样保留，人工审核/发布前自己检查处理。
        kept_paths.append(path)

    # 2026-08-18 按反馈取消了AI卖点图/产品信息图这两张文字卡片（detail_graphics.py还在，
    # 只是不再调用——以后想恢复不用重写）。详情页图片顺序变成：3张AI场景图 + N张允许保留的原商品图。
    scene_paths = [g.local_path for g in generated_images]
    ordered_images = scene_paths + kept_paths

    # 2026-08-14修正：长图（辅助长图）在拼多多上是用于搜索/推荐等流量场景的单独素材，
    # 不是详情页内容本身——之前理解错了，以为把全部图片拼进长图就等于填好了详情页。
    # 真正决定详情页内容的是"商品轮播图"（表单本身写了"若未编辑，轮播图将自动填充至图文详情"），
    # 所以改成把全部图片（AI图+graphics卡片+原图）都放进轮播图，轮播图上限10张，超出的截断。
    carousel_images = ordered_images[:10]
    if len(ordered_images) > 10:
        print(f"      [警告] 图片总数{len(ordered_images)}张超过轮播图上限10张，已截断，多出的{len(ordered_images) - 10}张图片没有放进轮播图")

    preview = DetailPagePreview(
        goods_id=product.source_goods_id,
        copy=copy,
        ordered_images=ordered_images,
        keywords=keywords,
        carousel_images=carousel_images,
        white_bg_image=scene_paths[0] if scene_paths else "",
    )

    _write_manifest(preview, output_dir)
    _write_html_preview(product, preview, output_dir)
    _write_detail_page(preview, output_dir)
    return preview


def _write_manifest(preview: DetailPagePreview, output_dir: str) -> None:
    path = os.path.join(output_dir, "manifest.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(asdict(preview), f, ensure_ascii=False, indent=2)


def _write_html_preview(product: ProductData, preview: DetailPagePreview, output_dir: str) -> None:
    def rel(p: str) -> str:
        return os.path.relpath(p, output_dir).replace("\\", "/")

    original_images_html = "".join(
        f'<img src="{img.url}" style="width:140px;margin:4px;border:1px solid #ccc">'
        for img in product.images[:8]
    )
    new_images_html = "".join(
        f'<img src="{rel(p)}" style="width:140px;margin:4px;border:1px solid #ccc">'
        for p in preview.ordered_images
    )
    bullets_html = "".join(f"<li>{b}</li>" for b in preview.copy.bullet_points)
    keywords_html = ", ".join(f"{k.term}({k.relevance})" for k in preview.keywords)

    html = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>预览 - {product.source_goods_id}</title></head>
<body style="font-family:sans-serif;max-width:1200px;margin:20px auto;">
<h2>商品改款预览（人工审核用，未发布）</h2>
<div style="display:flex;gap:40px;">
  <div style="flex:1;">
    <h3>原商品</h3>
    <p>标题：{product.title}</p>
    <p>价格：{product.price}</p>
    <div>{original_images_html}</div>
  </div>
  <div style="flex:1;">
    <h3>改款后</h3>
    <p>标题：{preview.copy.title}</p>
    <ul>{bullets_html}</ul>
    <p>详情文案：{preview.copy.description}</p>
    <p>候选关键词：{keywords_html}</p>
    <div>{new_images_html}</div>
  </div>
</div>
</body></html>"""

    with open(os.path.join(output_dir, "preview.html"), "w", encoding="utf-8") as f:
        f.write(html)


def _write_detail_page(preview: DetailPagePreview, output_dir: str) -> None:
    """模拟真实手机端商品详情页从上到下滚动的效果——这个页面里的图片顺序和内容，
    就是以后 Module 07 发布时会原样传给拼多多的那组详情图，不是给人工对比用的，是"发布件"本身的预览。
    """

    def rel(p: str) -> str:
        return os.path.relpath(p, output_dir).replace("\\", "/")

    images_html = "".join(f'<img src="{rel(p)}" class="detail-img">' for p in preview.ordered_images)

    html = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>详情页 - {preview.goods_id}</title>
<style>
  body {{ margin: 0; background: #e5e5e5; font-family: "Microsoft YaHei", sans-serif; }}
  .phone {{ width: 480px; margin: 24px auto; background: #fff; box-shadow: 0 0 20px rgba(0,0,0,.15); }}
  .detail-img {{ display: block; width: 100%; }}
  .hint {{ text-align: center; color: #888; font-size: 13px; padding: 12px; }}
</style></head>
<body>
<div class="hint">下面是模拟手机端从上到下滚动的详情页效果，图片顺序即发布时的真实顺序</div>
<div class="phone">{images_html}</div>
</body></html>"""

    with open(os.path.join(output_dir, "detail_page.html"), "w", encoding="utf-8") as f:
        f.write(html)
