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

import base64
import os
import shutil

from .config import Settings
from .llm_client import call_with_backoff, image_client
from .utils import download_file

PERSONA_DIR = "assets/model_personas"
CANDIDATE_DIR = "assets/model_personas/candidates"

_PERSONA_PORTRAIT_PROMPT_TEMPLATE = """真实商业人像摄影，纯人物标准照，用于后续多张不同商品图里保持同一个人物身份的参考底图，不涉及任何具体商品。
{model_block}
纯浅灰色摄影棚背景，无任何道具、无任何服装商品（可以穿一条基础款深色平角内裤，没有明显图案或logo，避免被误认成具体商品），
人物自然站立，正面朝向镜头，双臂略微离开身体两侧，方便看清体型、肤质和五官。
这张图的唯一目的是记录这个人物的脸和体型作为身份参考，不需要任何场景元素、器械或道具。"""


def persona_path(codename: str) -> str:
    return os.path.join(PERSONA_DIR, f"{codename}.png")


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
    不存在的话（第一次用这个代号）就直接生成一张定下来，不走候选流程——
    候选挑选是给"已经有一版但想换一张"这种场景用的，第一次用某个代号没有旧版本可比较，没必要多此一举。
    """
    path = persona_path(codename)
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return path
    return _generate_one(model_block, settings, path)
