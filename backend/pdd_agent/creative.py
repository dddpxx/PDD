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

import hashlib
import os
import zlib

from . import comfy_client, personas
from .config import Settings
from .models import GeneratedImage, ProductAnalysis, ProductData
from .utils import download_file

_NEGATIVE_PROMPT = (
    "different person, identity drift, wrong viewing angle, head turning back, body twist, mirrored garment, "
    "product front shown on the back, copied posing briefs from Picture 1, changed color, cut, logo, pattern, "
    "or fabric, shirt, trousers, props, visible eyes, full face, forehead, calves, feet, wide shot, deformed "
    "hands, extra fingers, plastic skin, blurred texture, watermark, text artifacts, cartoon, CGI"
)

_SCENE_PROMPT_TEMPLATE = """真实商业内衣商品摄影，人物{scene}。
Picture 1 是人物身份和当前拍摄角度参考：保持代号 {persona_codename} 的同一张脸、体型、肤色、胡茬和身体比例，并严格保持该视角，头部与躯干不得反向转动。
Picture 2 是商品参考：只把 Picture 1 的基础内裤替换为 Picture 2 的商品，准确保留颜色、剪裁、腰头、logo、图案、缝线和面料纹理，不能照抄 Picture 1 的内裤。
正面和侧面展示商品对应方向；背面镜头只展示商品背面，不得出现正面门襟、开口或囊袋结构。人物上半身赤裸，下半身只穿该商品，站姿自然放松，不添加道具或其它服装。
使用干净的 {background_color} 莫兰迪纯色摄影棚背景，柔和 45 度方向光，真实皮肤、体毛、手部和面料褶皱。
最终商品图固定为鼻梁位置至膝盖以上的近景裁切，不露眼睛、额头、小腿和脚；商品完整、清晰、光线充足，重点展示{feature_hint}。"""

# 2026-08-18 按反馈从"健身房场景"完全改成纯色摄影棚背景，只保留人物三个朝向（正面/侧面/背面），
# 不再需要具体姿势/器械互动的场景描述。
_STUDIO_POSE_SCENES: list[tuple[str, str]] = [
    ("正面面对镜头，头部与躯干均朝正面，双手自然垂放身体两侧", "FRONT_000"),
    ("左侧面面对镜头，头部与躯干均保持左侧面，双手自然垂放身体两侧", "LEFT_090"),
    ("背面面对镜头，头部与躯干均朝向背面，双手自然垂放身体两侧", "BACK_180"),
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


def _scene_output_filename(
    codename: str, persona_ref_path: str, scene: str,
    product_ref_path: str | None = None, prompt: str = "",
) -> str:
    reference = os.path.splitext(os.path.basename(persona_ref_path))[0]
    version = hashlib.sha256(prompt.encode("utf-8"))
    with open(persona_ref_path, "rb") as f:
        version.update(f.read())
    if product_ref_path:
        with open(product_ref_path, "rb") as f:
            version.update(f.read())
    identity_version = version.hexdigest()[:12]
    return f"{codename}_{reference}_{identity_version}_{scene}.png".replace("/", "_")


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
    comfy_client.validate_reference_models(settings)
    persona_refs = {
        view_id: personas.persona_reference_path(settings.persona_codename, view_id)
        for _, view_id in _STUDIO_POSE_SCENES
    }
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
    background_color = _background_color(product.source_goods_id)
    product_ref_path = product_ref_paths[0]

    results: list[GeneratedImage] = []
    scenes_dir = os.path.join(output_dir, "scenes")
    os.makedirs(scenes_dir, exist_ok=True)

    for scene, view_id in _STUDIO_POSE_SCENES:
        persona_ref_path = persona_refs[view_id]
        prompt = _SCENE_PROMPT_TEMPLATE.format(
            scene=scene,
            feature_hint=feature_hint,
            persona_codename=settings.persona_codename,
            background_color=background_color,
        )
        out_path = os.path.join(
            scenes_dir,
            _scene_output_filename(
                settings.persona_codename, persona_ref_path, scene, product_ref_path,
                prompt + _NEGATIVE_PROMPT + settings.comfy_qwen_unet_name
                + settings.comfy_qwen_clip_name + settings.comfy_qwen_vae_name,
            ),
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
