"""Module 05 生图后端：本地 ComfyUI。

两条路径都调用同一个 ComfyUI 实例（DAPENG 那套 Desktop 安装，监听在 8189——本机同时装了
两套 ComfyUI，另一套是无关的 MiniMax-H3，端口8188，不要跟8189搞混）：

- generate_image()：Z-Image-Turbo，纯文生图，没有图像输入节点，商品/人物一致性完全靠 prompt
  文字描述撑，实测对不上真实商品的具体印花/logo/面料图案（2026-08-17 用真实商品验证过，
  生成结果跟原图对不上），换取的是速度快、本地资源占用小。
- generate_image_with_references()：Qwen-Image-Edit-2509，能传参考图做图像编辑，商品/人物
  一致性靠图像条件锁定，不是靠文字硬猜——2026-08-17按反馈从 z_image_turbo 切回这条路径，
  因为商品一致性对这个项目是硬要求。实测配方：不开 Lightning 4步加速LoRA（会让人物皮肤/质感
  变得像插画，"AI感"重），用完整20步+cfg2.5（Comfy官方推荐的"高质量"档位，比50步/cfg4.0快
  但比4步/cfg1的Lightning版本慢很多，一张图在这台12GB显存的机器上大概要几分钟），生成后不要
  再过任何超分辨率模型（试过 4x-UltraSharp，会在暗色区域生成假的网状纹理伪影，越描越花）。

requests 会读 HTTP_PROXY/HTTPS_PROXY 环境变量，本机这两个变量指向一个只认外网域名的
代理，转发 127.0.0.1 请求会直接 502——所以这里所有请求都显式设置空代理地址绕开，
不依赖调用方有没有设置 NO_PROXY。
"""

from __future__ import annotations

import os
import random
import time
import uuid

import requests

from .config import Settings

_NO_PROXY = {"http": "", "https": ""}


def validate_reference_models(settings: Settings) -> None:
    """上传参考图前检查编辑能力，给出缺失模型清单。"""
    resp = requests.get(f"{settings.comfy_base_url}/object_info", proxies=_NO_PROXY, timeout=30)
    resp.raise_for_status()
    info = resp.json()
    missing = []
    for node, field, name in (
        ("UNETLoader", "unet_name", settings.comfy_qwen_unet_name),
        ("CLIPLoader", "clip_name", settings.comfy_qwen_clip_name),
        ("VAELoader", "vae_name", settings.comfy_qwen_vae_name),
    ):
        choices = info.get(node, {}).get("input", {}).get("required", {}).get(field, [[]])[0]
        if name not in choices:
            missing.append(name)
    if "TextEncodeQwenImageEditPlus" not in info:
        missing.append("TextEncodeQwenImageEditPlus 节点")
    if missing:
        raise RuntimeError("参考图编辑不可用，缺少: " + ", ".join(missing) +
                           "。Z-Image 文生图不能替代人物/商品参考图编辑。")


def _queue_prompt(settings: Settings, workflow: dict) -> str:
    resp = requests.post(
        f"{settings.comfy_base_url}/prompt",
        json={"prompt": workflow, "client_id": f"pdd-agent-{uuid.uuid4()}"},
        proxies=_NO_PROXY,
        timeout=30,
    )
    result = resp.json()
    if result.get("error"):
        raise RuntimeError(f"ComfyUI 拒绝了这次生图请求: {result}")
    resp.raise_for_status()
    return result["prompt_id"]


def _wait_for_result(settings: Settings, prompt_id: str, timeout: float) -> dict:
    start = time.time()
    while time.time() - start < timeout:
        resp = requests.get(f"{settings.comfy_base_url}/history/{prompt_id}", proxies=_NO_PROXY, timeout=10)
        resp.raise_for_status()
        history = resp.json()
        if prompt_id in history:
            return history[prompt_id]
        time.sleep(3)
    raise TimeoutError(f"ComfyUI 生图请求 {prompt_id} 超过 {timeout:.0f} 秒未完成，本地服务可能卡住了，去 ComfyUI 界面看一眼队列")


def _download_result(settings: Settings, result: dict, out_path: str, save_node_id: str = "9") -> None:
    status = result.get("status", {})
    if status.get("status_str") == "error":
        raise RuntimeError(f"ComfyUI 生图失败: {status}")

    images = result.get("outputs", {}).get(save_node_id, {}).get("images", [])
    if not images:
        raise RuntimeError(f"ComfyUI 没有返回图片，outputs={result.get('outputs')}")

    img = images[0]
    resp = requests.get(
        f"{settings.comfy_base_url}/view",
        params={"filename": img["filename"], "subfolder": img.get("subfolder", ""), "type": img.get("type", "output")},
        proxies=_NO_PROXY,
        timeout=30,
    )
    resp.raise_for_status()
    part_path = f"{out_path}.part"
    with open(part_path, "wb") as f:
        f.write(resp.content)
    os.replace(part_path, out_path)


def _upload_image(settings: Settings, local_path: str) -> str:
    """把本地图片上传到 ComfyUI 的 input 目录，返回 ComfyUI 那边认得的文件名（LoadImage 节点用这个）。"""
    with open(local_path, "rb") as f:
        resp = requests.post(
            f"{settings.comfy_base_url}/upload/image",
            files={"image": (os.path.basename(local_path), f, "application/octet-stream")},
            proxies=_NO_PROXY,
            timeout=60,
        )
    resp.raise_for_status()
    uploaded = resp.json()
    return "/".join(part for part in (uploaded.get("subfolder", ""), uploaded["name"]) if part)


# ---- Z-Image-Turbo：纯文生图（无参考图能力，见模块docstring里的取舍说明） ----


def _build_workflow(settings: Settings, prompt_text: str, width: int, height: int, steps: int, seed: int) -> dict:
    return {
        "28": {"class_type": "UNETLoader", "inputs": {"unet_name": settings.comfy_unet_name, "weight_dtype": "default"}},
        "30": {"class_type": "CLIPLoader", "inputs": {"clip_name": settings.comfy_clip_name, "type": "lumina2", "device": "default"}},
        "29": {"class_type": "VAELoader", "inputs": {"vae_name": settings.comfy_vae_name}},
        "27": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["30", 0], "text": prompt_text}},
        "33": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["27", 0]}},
        "13": {"class_type": "EmptySD3LatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}},
        "11": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["28", 0], "shift": 3}},
        "3": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["11", 0],
                "positive": ["27", 0],
                "negative": ["33", 0],
                "latent_image": ["13", 0],
                "seed": seed,
                "steps": steps,
                "cfg": 1,
                "sampler_name": "res_multistep",
                "scheduler": "simple",
                "denoise": 1,
            },
        },
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["29", 0]}},
        "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": "pdd-scene"}},
    }


def generate_image(
    settings: Settings,
    prompt: str,
    out_path: str,
    width: int = 1024,
    height: int = 1024,
    steps: int = 8,
    seed: int | None = None,
) -> None:
    """调用本地 ComfyUI（Z-Image-Turbo）按文本 prompt 生成一张图，存到 out_path。不接受参考图。"""
    if seed is None:
        seed = random.randint(0, 2**31 - 1)
    workflow = _build_workflow(settings, prompt, width, height, steps, seed)
    prompt_id = _queue_prompt(settings, workflow)
    result = _wait_for_result(settings, prompt_id, timeout=300)
    _download_result(settings, result, out_path)


# ---- Qwen-Image-Edit-2509：带参考图的图像编辑（商品/人物一致性靠这个锁） ----


def _build_qwen_edit_workflow(
    settings: Settings,
    persona_name: str,
    product_name: str | None,
    prompt_text: str,
    negative_prompt: str,
    steps: int,
    cfg: float,
    seed: int,
    outpaint_padding: tuple[int, int, int, int] | None = None,
) -> dict:
    workflow = {
        "37": {"class_type": "UNETLoader", "inputs": {"unet_name": settings.comfy_qwen_unet_name, "weight_dtype": "default"}},
        "38": {"class_type": "CLIPLoader", "inputs": {"clip_name": settings.comfy_qwen_clip_name, "type": "qwen_image", "device": "default"}},
        "39": {"class_type": "VAELoader", "inputs": {"vae_name": settings.comfy_qwen_vae_name}},
        "66": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["37", 0], "shift": 3.0}},
        "75": {"class_type": "CFGNorm", "inputs": {"model": ["66", 0], "strength": 1.0, "pre_cfg": False}},
        "78a": {"class_type": "LoadImage", "inputs": {"image": persona_name}},
        "117": {"class_type": "FluxKontextImageScale", "inputs": {"image": ["78a", 0]}},
        "88": {"class_type": "VAEEncode", "inputs": {"pixels": ["117", 0], "vae": ["39", 0]}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["39", 0]}},
        "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": "pdd-scene"}},
        "3": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["75", 0], "positive": ["111", 0], "negative": ["110", 0], "latent_image": ["88", 0],
                "seed": seed, "steps": steps, "cfg": cfg, "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0,
            },
        },
    }
    identity_image = ["117", 0]
    if outpaint_padding:
        left, top, right, bottom = outpaint_padding
        workflow["118"] = {
            "class_type": "ImagePadForOutpaint",
            "inputs": {
                "image": ["78a", 0],
                "left": left,
                "top": top,
                "right": right,
                "bottom": bottom,
                "feathering": 32,
            },
        }
        workflow["88"] = {
            "class_type": "VAEEncodeForInpaint",
            "inputs": {"pixels": ["118", 0], "vae": ["39", 0], "mask": ["118", 1], "grow_mask_by": 8},
        }
        identity_image = ["118", 0]
    text_encode_inputs = {"clip": ["38", 0], "vae": ["39", 0], "image1": identity_image}
    if product_name:
        workflow["78b"] = {"class_type": "LoadImage", "inputs": {"image": product_name}}
        text_encode_inputs["image2"] = ["78b", 0]
    workflow["111"] = {"class_type": "TextEncodeQwenImageEditPlus", "inputs": {**text_encode_inputs, "prompt": prompt_text}}
    workflow["110"] = {"class_type": "TextEncodeQwenImageEditPlus", "inputs": {**text_encode_inputs, "prompt": negative_prompt}}
    return workflow


def generate_image_with_references(
    settings: Settings,
    prompt: str,
    negative_prompt: str,
    persona_path: str,
    product_path: str | None,
    out_path: str,
    steps: int = 20,
    cfg: float = 2.5,
    seed: int | None = None,
    outpaint_padding: tuple[int, int, int, int] | None = None,
) -> None:
    """调用本地 ComfyUI（Qwen-Image-Edit-2509）按参考图 + 文本 prompt 生成一张图，存到 out_path。

    persona_path 是人物身份参考图（第一张，同时决定输出画布的尺寸），product_path 是商品参考图
    （可选，第二张）。不开 Lightning LoRA、steps=20/cfg=2.5 是实测验证过的"照片感 vs 速度"平衡点，
    详见模块开头注释——不要为了"追更清晰"擅自加超分辨率后处理，会引入伪影。
    """
    if seed is None:
        seed = random.randint(0, 2**31 - 1)
    validate_reference_models(settings)
    persona_name = _upload_image(settings, persona_path)
    product_name = _upload_image(settings, product_path) if product_path else None
    workflow = _build_qwen_edit_workflow(
        settings, persona_name, product_name, prompt, negative_prompt, steps, cfg, seed, outpaint_padding
    )
    prompt_id = _queue_prompt(settings, workflow)
    # Qwen-Image-Edit 模型比 z_image_turbo 大得多（~20GB+9GB），这台12GB显存的机器要靠CPU/显存
    # 换入换出，第一次加载模型加上20步采样实测要4-6分钟，超时给宽松点，别把正常耗时误判成卡死。
    result = _wait_for_result(settings, prompt_id, timeout=900)
    _download_result(settings, result, out_path)
