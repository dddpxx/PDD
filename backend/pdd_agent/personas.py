"""模特人设一致性（代号系统）。

gpt-image 的 images.edit/generate 之间没有"记住上次生成的脸"这回事，每次调用都是独立生成——
只靠文字描述"一个28-38岁的亚洲男性"，不同商品之间会长成完全不同的人，没法说是"同一个模特代言"。
这个API也没有"种子"参数，同一句prompt重新生成一次，脸和体型都会是全新的、没法精确复现上一次的结果。

做法：先单独生成这个人设的"标准照"候选（纯人物+体型，不带任何商品/场景），人工挑一张满意的确定下来，
存成一个代号对应的文件，以后生成场景图时把这张标准照也当参考图一起传进去，让新图的人脸/体型往这张标准照上靠拢。
这不是100%稳定的"同一个人"（gpt-image 没有 LoRA/embedding 级别的身份锁定能力），
但比"每次都用纯文字重新描述一遍"要一致得多。

2026-08-12教训：曾经在没有备份的情况下直接删掉旧的标准照重新生成，结果新的人脸不如旧的好看，
而且没法复原（没存备份、也没法用同一个prompt精确复现）。之后改成：候选图统一存到 candidates/ 子目录，
不会自动覆盖任何东西；"确定用哪张"是显式调用 promote_candidate() 才会发生的动作。
"""

from __future__ import annotations

import argparse
import base64
import configparser
import os
import shutil
import tempfile

from PIL import Image, ImageChops, ImageOps

from . import comfy_client
from .config import Settings, load_settings
from .llm_client import call_with_backoff, image_client
from .utils import download_file

PERSONA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "model_personas")
CANDIDATE_DIR = os.path.join(PERSONA_DIR, "candidates")

_PERSONA_PORTRAIT_PROMPT_TEMPLATE = """真实商业人像摄影，纯人物标准照，用于后续多张不同商品图里保持同一个人物身份的参考底图，不涉及任何具体商品。
{model_block}
纯浅灰色摄影棚背景，无任何道具、无任何服装商品（可以穿一条基础款深色平角内裤，没有明显图案或logo，避免被误认成具体商品），
人物自然站立，正面朝向镜头，双臂略微离开身体两侧，方便看清体型、肤质和五官。
这张图的唯一目的是记录这个人物的脸和体型作为身份参考，不需要任何场景元素、器械或道具。"""


def persona_path(codename: str) -> str:
    nested = os.path.join(PERSONA_DIR, codename, f"{codename}.png")
    return nested if os.path.exists(nested) else os.path.join(PERSONA_DIR, f"{codename}.png")


def persona_reference_path(codename: str, view_id: str) -> str:
    path = os.path.join(PERSONA_DIR, codename, "identity", f"{view_id}.png")
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return path
    raise FileNotFoundError(f"缺少已确认的 {view_id} 人物参考图: {path}；不能用其它视角代替。")


def load_identity_prompts() -> tuple[str, str, list[tuple[str, str]]]:
    def read(name: str) -> str:
        with open(os.path.join(PERSONA_DIR, name), encoding="utf-8") as f:
            return f.read().strip()

    parser = configparser.ConfigParser(interpolation=None)
    parser.read(os.path.join(PERSONA_DIR, "人物六视图.txt"), encoding="utf-8")
    views = [(section, parser.get(section, "prompt").strip()) for section in parser.sections()]
    return read("人物共用总提示词.txt"), read("附加提示词.txt"), views


def _prepare_identity_reference(source: str, target: str) -> None:
    with Image.open(source) as image:
        image = image.convert("RGB")
        width, height = image.size
        crop = image.crop((int(width * 0.12), int(height * 0.16), int(width * 0.88), height))
        crop.thumbnail((700, 780), Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", (768, 1024), (128, 128, 128))
        canvas.paste(crop, ((768 - crop.width) // 2, 0))
        canvas.save(target)


def _prepare_outpaint_reference(source: str, target: str) -> None:
    with Image.open(source) as image:
        image = image.convert("RGB")
        image.thumbnail((585, 780), Image.Resampling.LANCZOS)
        image.save(target)


def _is_valid_identity_view(path: str) -> bool:
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return False
    try:
        with Image.open(path) as image:
            return image.size == (768, 1024)
    except OSError:
        return False


def _normalize_identity_view(path: str) -> None:
    with Image.open(path) as image:
        image = image.convert("RGB")
        if max(abs(channel - 128) for channel in image.getpixel((0, 0))) <= 8:
            difference = ImageChops.difference(image, Image.new("RGB", image.size, (128, 128, 128)))
            borderless = difference.convert("L").point(lambda value: 255 if value > 12 else 0).getbbox()
            if borderless:
                image = image.crop(borderless)
        if image.size == (768, 1024):
            return
        normalized = ImageOps.fit(image, (768, 1024), Image.Resampling.LANCZOS)
        part_path = f"{path}.normalize.part"
        normalized.save(part_path, format="PNG")
    os.replace(part_path, path)


def _crop_profile_to_knees(path: str) -> None:
    with Image.open(path) as image:
        cropped = image.convert("RGB").crop((84, 0, 684, 800)).resize((768, 1024), Image.Resampling.LANCZOS)
        part_path = f"{path}.profile.part"
        cropped.save(part_path, format="PNG")
    os.replace(part_path, path)


def generate_identity_views(codename: str, settings: Settings, seed: int | None = None) -> list[str]:
    source = persona_path(codename)
    if not os.path.exists(source):
        raise FileNotFoundError(f"找不到人设源图: {source}")

    common, negative, views = load_identity_prompts()
    identity_dir = os.path.join(PERSONA_DIR, codename, "identity")
    os.makedirs(identity_dir, exist_ok=True)
    results: list[str] = []

    with tempfile.NamedTemporaryFile(dir=identity_dir, suffix=".png", delete=False) as reference:
        reference_path = reference.name
    try:
        _prepare_identity_reference(source, reference_path)
        front_path = os.path.join(identity_dir, "FRONT_000.png")
        for view_index, (view_id, view_prompt) in enumerate(views):
            out_path = os.path.join(identity_dir, f"{view_id}.png")
            view_seed = None if seed is None else seed + view_index
            if _is_valid_identity_view(out_path):
                print(f"{view_id} 已存在，跳过")
            else:
                if view_id == "FRONT_000" or not _is_valid_identity_view(front_path):
                    generation_reference = reference_path
                    framing_instruction = (
                        "Preserve its top crop exactly; never restore the missing eyes, forehead, or hair. "
                        "Replace the blank gray lower area with a seamless continuation of the same thighs "
                        "through both kneecaps; leave no gray bar."
                    )
                else:
                    generation_reference = front_path
                    framing_instruction = (
                        "Rotate only the same person to the requested view. Preserve Picture 1's exact subject "
                        "scale, nasal-bridge top crop, knee-level bottom crop, complete arms and hands, and skin texture. "
                        "Do not zoom, reframe, or restore the missing upper head."
                    )
                comfy_client.generate_image_with_references(
                    settings,
                    f"Picture 1 is the sole identity and composition authority. {framing_instruction}"
                    f"\n\n{common}\n\n{view_prompt}",
                    negative,
                    generation_reference,
                    None,
                    out_path,
                    seed=view_seed,
                )
                _normalize_identity_view(out_path)
                if view_id != "FRONT_000":
                    with tempfile.NamedTemporaryFile(dir=identity_dir, suffix=".png", delete=False) as outpaint:
                        outpaint_path = outpaint.name
                    try:
                        _prepare_outpaint_reference(out_path, outpaint_path)
                        comfy_client.generate_image_with_references(
                            settings,
                            f"Picture 1 already has the exact final identity and {view_id} angle. Preserve all "
                            "visible anatomy, the nasal-bridge top crop, complete arms, hands, clothing, and skin. "
                            "Outpaint only the masked left, right, and lower regions: continue the neutral studio "
                            "background and extend both thighs naturally through both kneecaps; leave no seam or blank area."
                            f"\n\n{common}\n\n{view_prompt}",
                            negative,
                            outpaint_path,
                            None,
                            out_path,
                            seed=view_seed,
                            outpaint_padding=(91, 0, 92, 244),
                        )
                        _normalize_identity_view(out_path)
                        if view_id.endswith("_090"):
                            _crop_profile_to_knees(out_path)
                    finally:
                        if os.path.exists(outpaint_path):
                            os.remove(outpaint_path)
            results.append(out_path)
    finally:
        if os.path.exists(reference_path):
            os.remove(reference_path)

    return results


def _candidate_path(codename: str, index: int) -> str:
    return os.path.join(CANDIDATE_DIR, f"{codename}_candidate_{index}.png")


def _save_generated_image(result: object, path: str) -> None:
    if getattr(result, "b64_json", None):
        with open(path, "wb") as f:
            f.write(base64.b64decode(result.b64_json))
    elif getattr(result, "url", None):
        download_file(result.url, path)
    else:
        raise RuntimeError(f"生图接口既没返回b64_json也没返回url：{result!r}")


def _generate_one(model_block: str, settings: Settings, out_path: str) -> str:
    client = image_client(settings)
    prompt = _PERSONA_PORTRAIT_PROMPT_TEMPLATE.format(model_block=model_block)

    def _generate() -> object:
        return client.images.generate(model=settings.image_model, prompt=prompt, size="1024x1024")

    resp = call_with_backoff(_generate)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    _save_generated_image(resp.data[0], out_path)
    return out_path


def generate_candidates(codename: str, model_block: str, settings: Settings, count: int = 3) -> list[str]:
    """生成N张候选标准照，不影响已经存在的"确定版"人设文件。"""
    return [_generate_one(model_block, settings, _candidate_path(codename, i)) for i in range(count)]


def promote_candidate(codename: str, candidate_path: str) -> str:
    """把选中的候选图确定为这个代号的正式标准照。如果之前已经有正式版，先备份，不直接覆盖丢失。"""
    path = persona_path(codename)
    if os.path.exists(path):
        backup_dir = os.path.join(PERSONA_DIR, "history")
        os.makedirs(backup_dir, exist_ok=True)
        n = 1
        while os.path.exists(os.path.join(backup_dir, f"{codename}_{n}.png")):
            n += 1
        shutil.copy2(path, os.path.join(backup_dir, f"{codename}_{n}.png"))
    os.makedirs(PERSONA_DIR, exist_ok=True)
    shutil.copy2(candidate_path, path)
    return path


def get_or_create_persona(codename: str, model_block: str, settings: Settings) -> str:
    """场景生成时调用：代号对应的正式标准照如果已经存在就直接复用；
    缺失时停止，避免自动换人；新人物须通过候选流程确认。
    """
    path = persona_path(codename)
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return path
    raise FileNotFoundError(f"找不到已确认的人物母模: {path}；请接入指定母模，不会自动生成新人物。")


def main() -> None:
    parser = argparse.ArgumentParser(description="人物母模工具")
    subparsers = parser.add_subparsers(dest="command", required=True)
    six_views = subparsers.add_parser("six-views", help="串行生成六视角人物母模")
    six_views.add_argument("codename")
    six_views.add_argument("--seed", type=int)
    args = parser.parse_args()

    from dotenv import load_dotenv

    load_dotenv()
    os.environ.setdefault("OPENAI_TEXT_API_KEY", "unused")
    generate_identity_views(args.codename, load_settings(), seed=args.seed)


if __name__ == "__main__":
    main()
