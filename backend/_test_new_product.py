"""导入新商品链接，跑完整流程但AI场景图这一步借用旧商品(981833693052)已经生成好的图，
先把发布自动化流程走通，不重复花钱/花时间生成新图。用完即删。"""

import glob
import os

from dotenv import load_dotenv

load_dotenv()

from pdd_agent import analyzer, copywriter, detail_builder, importer, keywords
from pdd_agent.auth import load_cookies_for_requests
from pdd_agent.config import load_settings
from pdd_agent.models import GeneratedImage

URL = "https://mobile.yangkeduo.com/goods1.html?ps=lcWSnHuVhB"
BORROWED_SCENES_DIR = "output/981833693052/scenes"

settings = load_settings()
cookies = load_cookies_for_requests("pdd_login_state.json")

print("[1/5] 导入商品")
product = importer.import_product(URL, cookies=cookies)
print(f"      -> {product.title} | 价格 {product.price} | {len(product.images)}张图 | {len(product.skus)}个SKU")

output_dir = os.path.join(settings.output_dir, product.source_goods_id)
os.makedirs(output_dir, exist_ok=True)

print("[2/5] 分析商品 + 图片分类")
analysis = analyzer.analyze_product(product, settings)
analyzer.classify_images(product, settings)
kept = sum(1 for i in product.images if i.tag == "KEEP")
print(f"      -> KEEP图 {kept}/{len(product.images)}")

print("[3/5] 生成候选关键词")
kw = keywords.generate_keywords(product, analysis, settings)

print("[4/5] 生成文案")
copy = copywriter.generate_copy(analysis, kw, settings)
print(f"      -> 新标题: {copy.title}")

print("[5/5] 借用旧场景图，组装详情页预览")
borrowed_paths = sorted(glob.glob(os.path.join(BORROWED_SCENES_DIR, "*.png")))
generated_images = [
    GeneratedImage(scene_name=f"borrowed_{i}", local_path=p, prompt_used="(借用自981833693052，未重新生成)")
    for i, p in enumerate(borrowed_paths)
]
print(f"      -> 借用了 {len(generated_images)} 张旧场景图")

preview = detail_builder.build_detail_page(product, copy, kw, generated_images, output_dir)
print(f"      -> 预览已生成: {os.path.join(output_dir, 'preview.html')}")
print(f"      -> carousel_images 数量: {len(preview.carousel_images)}")
for p in preview.carousel_images:
    print("         ", p)
