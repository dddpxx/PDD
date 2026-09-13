import os
from dataclasses import dataclass


@dataclass
class Settings:
    # 文本模型（Module 02分析/03关键词/04文案，需要 chat/completions 权限）
    text_api_key: str
    text_base_url: str | None
    text_model: str
    # 图像模型（Module 05场景图，只需要 images 权限）——2026-08-17起 Module 05 默认改走本地
    # ComfyUI（见 comfy_client.py），这几个字段不再被 creative.py 使用，保留只是为了兼容还留着
    # 这份 .env 配置的情况，不强制要求填，personas.py 如果以后还要用 OpenAI 生成候选人设照可以继续用。
    image_api_key: str | None
    image_base_url: str | None
    image_model: str
    output_dir: str
    # 本地 ComfyUI（Z-Image-Turbo，纯文生图，见 comfy_client.py）。本机装了两套 ComfyUI，
    # 8188 是无关的 MiniMax-H3 装置，真正带 z_image_turbo 模型、随 Comfy Desktop 启动的是 8189。
    comfy_base_url: str
    comfy_unet_name: str
    comfy_clip_name: str
    comfy_vae_name: str
    # Qwen-Image-Edit-2509（能传参考图做图像编辑，商品/人物一致性靠这个锁，不是靠文字描述）
    comfy_qwen_unet_name: str
    comfy_qwen_clip_name: str
    comfy_qwen_vae_name: str
    # 模特人设代号（见 personas.py），默认使用用户指定的肌肉男，
    # 不同商品想用哪个人设跑，改 PDD_PERSONA_CODENAME 这个环境变量就行，不用改代码。
    persona_codename: str
    # Module 09 采购履约相关参数，对应 DM.md §4 D1 的拍板结论
    procurement_min_margin_rate: float  # 最低毛利率，低于这个直接判BLOCKED_LOW_MARGIN
    procurement_min_margin_absolute: float  # 最低毛利绝对值（元），两个条件都要过
    procurement_daily_spend_cap: float  # 每日采购总金额上限，独立于毛利率之外的资金闸门
    procurement_cutoff_hour: int  # D1.1：每天几点是采购批次的cutoff，默认18点


def load_settings() -> Settings:
    # 图像和文本分开配置，因为实测发现同一个"OpenAI兼容"中转key不一定两边权限都有
    # ——比如 sublyx 的 "PDD生图" key 分组只给了 gpt-image-1/1.5/2/2-firefly 这几个生图模型，
    # 调 chat/completions 会直接 404 model_not_found，所以不能假设一个key两边通用。
    # image_key 不再是硬性要求：Module 05 默认已经改走本地 ComfyUI（见 comfy_client.py），
    # 不需要这个key；只有还在用 personas.py 里 OpenAI 候选人设照生成那条老路径时才需要它。
    image_key = os.environ.get("OPENAI_IMAGE_API_KEY")
    text_key = os.environ.get("OPENAI_TEXT_API_KEY")
    if not text_key:
        raise RuntimeError(
            "OPENAI_TEXT_API_KEY 未设置。当前配的生图key实测只有 gpt-image-* 系列的权限，没有 chat/completions 权限，"
            "Module 02/03/04（商品分析/关键词/文案）需要另外一个能调文本对话模型的key，不能复用生图key。"
        )
    return Settings(
        text_api_key=text_key,
        text_base_url=os.environ.get("OPENAI_TEXT_BASE_URL") or None,
        text_model=os.environ.get("OPENAI_TEXT_MODEL", "gpt-5"),
        image_api_key=image_key,
        image_base_url=os.environ.get("OPENAI_IMAGE_BASE_URL") or None,
        image_model=os.environ.get("OPENAI_IMAGE_MODEL", "gpt-image-1"),
        output_dir=os.environ.get("PDD_AGENT_OUTPUT_DIR", "output"),
        comfy_base_url=os.environ.get("COMFY_BASE_URL", "http://100.83.253.18:8189"),
        comfy_unet_name=os.environ.get("COMFY_UNET_NAME", "z_image_turbo_bf16.safetensors"),
        comfy_clip_name=os.environ.get("COMFY_CLIP_NAME", "qwen_3_4b.safetensors"),
        comfy_vae_name=os.environ.get("COMFY_VAE_NAME", "ae.safetensors"),
        comfy_qwen_unet_name=os.environ.get("COMFY_QWEN_UNET_NAME", "qwen_image_edit_2509_fp8_e4m3fn.safetensors"),
        comfy_qwen_clip_name=os.environ.get("COMFY_QWEN_CLIP_NAME", "qwen_2.5_vl_7b_fp8_scaled.safetensors"),
        comfy_qwen_vae_name=os.environ.get("COMFY_QWEN_VAE_NAME", "qwen_image_vae.safetensors"),
        persona_codename=os.environ.get("PDD_PERSONA_CODENAME", "肌肉男"),
        procurement_min_margin_rate=float(os.environ.get("PDD_PROCUREMENT_MIN_MARGIN_RATE", "0.25")),
        procurement_min_margin_absolute=float(os.environ.get("PDD_PROCUREMENT_MIN_MARGIN_ABS", "8")),
        procurement_daily_spend_cap=float(os.environ.get("PDD_PROCUREMENT_DAILY_SPEND_CAP", "500")),
        procurement_cutoff_hour=int(os.environ.get("PDD_PROCUREMENT_CUTOFF_HOUR", "18")),
    )
