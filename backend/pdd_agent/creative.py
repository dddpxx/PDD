"""Module 05 - Creative Studio。调用本地 ComfyUI（Qwen-Image-Edit-2509）以人物/商品参考图生成场景图。

对应 DM.md §5 场景图模板系统。2026-08-17 从 gpt-image 的 images.edit 切换到本地 ComfyUI：
先试过 z_image_turbo（纯文生图，没有图像输入），实测商品的具体印花/logo/面料图案完全对不上
真实商品——纯文字描述没法精确还原一件具体商品长什么样，这是那条路径的硬伤，不是prompt能补的。
改用 Qwen-Image-Edit-2509（见 comfy_client.py），能把人物身份参考图 + 商品参考图当图像输入传进去，
一致性靠图像条件锁定，不是靠文字硬猜。代价是模型大（本地要占约30GB显存/内存）、单张生成慢
（这台12GB显存机器上一张图大概几分钟），比 z_image_turbo 慢很多，但商品一致性对这个项目是硬要求，
两者取舍下选了这条路径。
"""

from __future__ import annotations

import os
import zlib

from . import comfy_client, personas
from .config import Settings
from .models import GeneratedImage, ProductAnalysis, ProductData
from .utils import download_file

_NEGATIVE_PROMPT = (
    "AI-generated look, synthetic/plastic/waxy skin, overly smooth skin with no visible pores or body hair, "
    "uncanny-valley face, doll-like face, overly smooth or airbrushed skin, flat even studio lighting with no "
    "shadow direction, oversaturated colors, low detail, blurry, deformed hands, extra fingers, distorted "
    "logo, mismatched fabric pattern, gym equipment, furniture, props, background clutter, text artifacts, "
    "watermark, low resolution, cartoon, illustration, 3D render, CGI, wide full-body shot, visible eyes, "
    "visible full face."
)

_SCENE_PROMPT_TEMPLATE = """真实商业电商摄影棚拍风格，纯色摄影棚背景：{scene}。
背景是干净的莫兰迪色系乳胶漆纯色背景墙（{background_color}），没有任何道具、器械、家具或其他场景元素，
整组图（这个商品的所有场景）背景颜色必须保持完全一致，不要在不同场景之间换成别的颜色或质感。
本次提供了两类参考图，第一张是人物身份参考图（代号：{persona_codename}）——画面里这个人的脸、五官、体型、肤质、
胡茬都必须和这第一张参考图保持是同一个人，不能换成别的长相或体型；从第二张开始的参考图是本次要展示的商品本身。
画面主体必须是商品参考图里的这件商品本身，颜色、剪裁、logo、图案、轮廓都要和商品参考图保持一致，不能改变产品设计，
面料的纹理/针织图案/印花细节要严格按第二张开始的商品参考图临摹，不能凭空简化或改画成别的图案。
这里最容易出的错是把第一张人物身份参考图上那条本来就穿着的基础款内裤，当成了要展示的商品——一定要认清商品参考图是从第二张开始，
最终画面里的这条内裤，颜色/图案/logo/面料纹理必须去对照第二张开始的商品参考图，不能照抄第一张人物参考图里那条内裤的样子。
商品的穿着方向/正反面必须和参考图完全一致，不能镜像、不能反穿、不能把正面的图案/logo/标签穿到背面去。
不要凭空给人物添加参考图里没有的纹身、上衣、背心、绳索/器械道具等任何元素。
这一点尤其要注意视角一致性：如果这个场景是从人物背后拍摄（能看到背部、后腰、臀部），那么画面里内裤呈现的必须是这件商品的背面设计——
背面通常是素面、没有正面那种开口/门襟结构和明显的立体囊袋轮廓，不能出现"人物是背对镜头，但内裤却是正面开口结构朝着镜头"这种视角和商品部位对不上的错误；
只有当场景是从正面或侧前方拍摄、能看到人物身前时，才展示商品参考图里那种正面结构。
人物上半身赤裸，不穿任何上衣、外套、背心，下半身只穿参考图里的这条内裤（产品），不叠穿其他裤子。
内裤裆部的凸起幅度要偏小、偏收敛，宁可比真实平均水平再小一点、更平坦一些，也不要显得鼓包、隆起或者刻意展示轮廓——
裤型剪裁、松紧度必须和参考图一致，穿着状态是自然贴合、松量正常，不是刻意绷紧展示的夸张效果，构图也不要为了裆部特写而过度贴近镜头。
面料要有随身体自然产生的细微垂坠感、褶皱和纹理阴影，不要是光滑无褶、像塑料模型一样的圆顶形状，褶皱的自然感来自面料物理特性，不是刻意做出的形状。
商品上的品牌标签/logo不需要在每张图里都刻意露出——如果人物的动作姿态或拍摄角度自然遮挡了标签，遮住就遮住，不要为了让标签露出而扭曲产品剪裁、拉扯面料或摆出不合理的身体角度；
面料的褶皱走向、缝合线位置要符合人体动作和面料在真实物理张力下呈现的自然包裹感，该在哪就在哪，不要为了展示某个细节而人为改变这些自然位置。
这组图的核心目的是展示这条内裤本身（面料质感、剪裁版型、腰头细节），人物只是承载商品的载体，不是拍摄的主角——
构图上要让内裤这个产品清晰、完整、光线充足地出现在画面里，是"产品照带一点人像感"，不是"人像写真带一件产品"。
不要摆出刻意炫耀身材、挑逗或性张力暗示的姿势和表情（比如刻意绷紧鼓起肌肉对着镜头、挑眉、抿嘴这类姿态），
人物的站姿应该是自然放松的状态，表情平静自然，不是在对镜头摆拍展示身材。
{model_block}
构图是近景半身构图：画面上边缘从人物鼻梁以下开始入画（不露眼睛、鼻梁、额头），画面下边缘截止在膝盖以上，
不拍到小腿和脚，人物在画面里占比大、商品和上半身细节清晰可见，不是far shot那种能看到全身和大片背景的构图。
人物{scene}，是自然放松的静态站姿，不是刻意摆拍造型。
手部和手指的解剖结构必须正确、清晰、不模糊：每只手正常五根手指，形态自然，不要出现手指扭曲、多余或缺失手指、边缘模糊发虚这类AI生成瑕疵。
柔和的摄影棚方向光（比如45度侧光），不要死板的正面平光，光影要有自然的方向性和明暗对比，皮肤和面料的纹理细节在这种光线下要清晰可辨；
高级感，商业内衣广告摄影棚拍摄风格，不要出现除本商品外的其他品牌标识、文字水印、二维码。
突出商品的{feature_hint}。"""

# 2026-08-18 按反馈从"健身房场景"完全改成纯色摄影棚背景，只保留人物三个朝向（正面/侧面/背面），
# 不再需要具体姿势/器械互动的场景描述。
_STUDIO_POSE_SCENES: list[str] = [
    "正面面对镜头，双手自然垂放身体两侧，目视前方，展现商品正面结构",
    "身体侧对镜头、微微转头看向镜头方向，展现商品侧面轮廓和腰头剪裁",
    "背对镜头站立，头部侧转回望镜头，展现商品背面设计和腰线",
]

# 每个商品的三张场景图背景色要保持统一，但不同商品之间可以不一样——用 goods_id 做稳定哈希，
# 同一个商品重新生成/补跑时背景色不会变来变去，不用额外存状态。
_MORANDI_BACKGROUNDS: list[str] = [
    "雾霾灰绿色，muted sage grey-green",
    "豆沙灰粉色，dusty muted rose-mauve",
    "雾灰蓝色，soft dusty blue-grey",
    "燕麦卡其色，warm oatmeal taupe-grey",
    "浅灰紫色，muted lavender-grey",
    "浅可可棕灰色，soft mocha grey-brown",
]


def _background_color(goods_id: str) -> str:
    # 不能用内置 hash()：字符串的 hash() 每次进程启动都会被随机化（PYTHONHASHSEED），
    # 同一个商品重跑一次颜色就会变，跟"背景色统一、不重新计算"的目的正好相反。
    digest = zlib.crc32(goods_id.encode("utf-8"))
    return _MORANDI_BACKGROUNDS[digest % len(_MORANDI_BACKGROUNDS)]

# 模特人设按 Facts.gender 选用。z_image_turbo 没有 negative_prompt 参数，
# 所以"要避免的问题"也写成正面描述接在后面，而不是当成单独的API字段传。
_MODEL_PRESETS: dict[str, str] = {
    "男": (
        "Ultra-realistic photo of a visibly mature adult Asian man in his early-to-mid 30s (clearly an "
        "adult, not youthful-looking), bulky and burly muscular build, thick and solid muscle mass rather "
        "than lean cut fitness-model definition, broad thick shoulders, wide solid chest, thick arms, "
        "natural masculine body proportions, natural healthy tan Asian skin tone, realistic skin pores and "
        "texture, subtle veins, clearly visible natural body hair on the chest, abdomen and arms — individual "
        "hair strands should be sharply rendered and legible up close, not airbrushed away or blurred into a "
        "flat texture, matte dry skin texture, not oiled or glistening, no visible sweat. "
        "Standard mainstream retail underwear catalog photography, comparable in tone to a department-store "
        "or major clothing brand's basics catalog — NOT artistic nude photography, NOT fetish content, NOT "
        "adult content. The underwear fabric is fully opaque and non-see-through, providing complete, normal "
        "coverage exactly as a real garment would. Tasteful, modest commercial catalog photography suitable "
        "for a general-audience clothing e-commerce listing — the visual focus is the garment's fit and "
        "fabric, not the model's physique. "
        "Framing: the full face is NOT visible — no eyes, no nose bridge, no forehead. The top edge of the "
        "frame cuts straight across the face just below the bridge of the nose, so only the area from "
        "roughly the bottom of the nose down through the mouth, chin and jawline is in frame. What IS "
        "visible in that lower-face area should clearly show a 5-o'clock-shadow stubble with a slight "
        "blue-grey undertone from the dark shaved hair follicles beneath the skin (classic '青胡茬' look). "
        "Whatever part of the face is visible should look like a real photographed person, not a "
        "generated/synthetic face: realistic individual skin pores and fine texture, natural jaw/lip "
        "asymmetry, photographed straight from a real camera rather than airbrushed or over-retouched. "
        "Skin on both the visible face area and body is noticeably rough and coarse-textured, NOT smooth "
        "or flawless — clearly visible large skin pores (especially on nose, cheeks and upper back/shoulders), "
        "faint acne scars or small blemishes, slightly uneven skin tone with visible redness/patches, fine "
        "texture and micro-wrinkles, a bit of dry/rough patchiness — this should look like unretouched real "
        "skin under strong detailed lighting, closer to a raw phone photo of a real person's skin than a "
        "polished studio beauty shot. This roughness is a deliberate requirement, not a flaw to minimize. "
        "Photorealistic photography, highly detailed anatomy, realistic muscle definition, natural rough "
        "skin imperfections, subsurface scattering, natural directional light (not flat studio lighting), "
        "natural shadows, professional full-frame camera, 85mm lens, f/4, commercial catalog photography, RAW photo. "
        "Avoid: anime, illustration, painting, 3D render, CGI, doll-like face, plastic skin, waxy skin, "
        "overly smooth skin, airbrushed/over-retouched face, symmetrical perfect face, uncanny-valley "
        "synthetic look, overly smooth skin, excessive retouching, unrealistic bodybuilder steroid "
        "proportions, deformed anatomy, bad hands, extra fingers, extra limbs, asymmetrical eyes, blurry "
        "face, low resolution, oversaturated skin, oiled/glistening skin, female features, long hair, "
        "old man, teenager."
    ),
}


def _model_block(analysis: ProductAnalysis) -> str:
    # 实测 Module 02 给的 gender 是"男士"这种自由文本，不是精确的"男"，
    # 之前用精确匹配 _MODEL_PRESETS.get(gender) 一直命中不了，模特人设完全没生效过。
    # 改成包含匹配兜底，同时也该收紧 analyzer.py 里的 prompt 让它输出规范值，两边都要改。
    gender = analysis.facts.gender or ""
    for key, preset in _MODEL_PRESETS.items():
        if key in gender:
            return f"画面里的模特按以下人设生成：{preset}"
    return "画面里不强制出现真人模特，以商品本身和场景陈设为主。"


def _pick_reference_images(product: ProductData, max_count: int = 1) -> list[str]:
    # 这里故意不按 img.tag=="KEEP" 筛（那个tag是给detail_builder.py"能不能进最终详情页"用的，
    # 严格要求type=="product"且没有叠加文字）。参考图和"能不能直接进详情页复用"是两件不同的事：
    # 参考图只是给AI看"商品长什么样"，画面里有营销文字/水印不影响AI读出商品的颜色/剪裁/logo，
    # 但这种图绝对不能直接塞进最终详情页。优先用干净的product/model图；实在没有才退而求其次用text_info图。
    for allowed_types in (("product", "model"), ("product", "model", "text_info")):
        candidates = [img for img in product.images if img.type in allowed_types]
        if candidates:
            return [img.url for img in candidates[:max_count]]
    return []


def generate_scene_images(
    product: ProductData,
    analysis: ProductAnalysis,
    settings: Settings,
    output_dir: str,
) -> list[GeneratedImage]:
    reference_urls = _pick_reference_images(product)
    if not reference_urls:
        raise RuntimeError(
            "没有找到 type in (product/model/text_info) 的图片可以当商品参考图，"
            "先检查 Module 02 的图片分类结果是否合理。"
        )

    ref_dir = os.path.join(output_dir, "reference")
    product_ref_paths = [
        download_file(url, os.path.join(ref_dir, f"ref_{i}.jpg"))
        for i, url in enumerate(reference_urls)
    ]

    feature_hint = "、".join(analysis.selling_points[:2]) or "细节质感"
    model_block = _model_block(analysis)
    background_color = _background_color(product.source_goods_id)
    persona_ref_path = personas.get_or_create_persona(settings.persona_codename, model_block, settings)
    product_ref_path = product_ref_paths[0]

    results: list[GeneratedImage] = []
    scenes_dir = os.path.join(output_dir, "scenes")
    os.makedirs(scenes_dir, exist_ok=True)

    for scene in _STUDIO_POSE_SCENES:
        out_path = os.path.join(scenes_dir, f"{scene}.png".replace("/", "_"))
        prompt = _SCENE_PROMPT_TEMPLATE.format(
            scene=scene,
            feature_hint=feature_hint,
            model_block=model_block,
            persona_codename=settings.persona_codename,
            background_color=background_color,
        )

        # 复跑时跳过已经成功生成过的场景，只补生成之前失败/缺失的那几个——文件存在就等价于
        # 这个场景已经成功过，不用额外记状态（跟原来 gpt-image 版本的逻辑一致）。
        if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
            results.append(GeneratedImage(scene_name=scene, local_path=out_path, prompt_used=prompt))
            print(f"      场景「{scene}」已有生成结果，跳过重新生成")
            continue

        try:
            comfy_client.generate_image_with_references(
                settings, prompt, _NEGATIVE_PROMPT, persona_ref_path, product_ref_path, out_path
            )
        except Exception as e:
            # 单个场景失败不该拖垮整批已经生成成功的图，原因同旧版本注释：manifest/preview
            # 要能看到部分成功的结果，不能因为一个场景报错就让 Module 06 完全跑不到组装那一步。
            print(f"      场景「{scene}」生成失败，跳过，不影响其它场景：{e}")
            continue

        results.append(GeneratedImage(scene_name=scene, local_path=out_path, prompt_used=prompt))

    if not results:
        raise RuntimeError("这一轮所有场景图都生成失败了，看上面每条具体报错原因，不是走到组装那一步就会有预览。")

    return results
