"""Module 06 附属 - 卖点信息图生成。

对应 DM.md 里"AI核心卖点图/AI产品信息图"这一环：详情页不能只是"AI场景图 + 原图"两段拼接，
中间还需要有文字卖点的视觉呈现。这里没有用AI画图去生成带文字的图（AI模型画文字经常出现乱码/变形，
之前生成商品logo文字时就已经踩过这个坑），改用Pillow直接在代码里把文字画上去——
文字保证100%清晰可读，不会有AI生图那种文字失真问题，缺点是版式比较朴素，以后想做得更好看
可以在这基础上加背景图/图标素材，但"文字必须准确"这条不能退让。
"""

from __future__ import annotations

import os

from PIL import Image, ImageDraw, ImageFont

_FONT_DIR = "C:/Windows/Fonts"
_FONT_REGULAR = os.path.join(_FONT_DIR, "msyh.ttc")

_CARD_WIDTH = 880  # 之前800px+34号字很容易两行卖点就换行、显得挤，加宽一点给文字留够单行的空间

# 深色调配色跟AI场景图那边"健身房/金属质感"的调性呼应，白色卡片用来在长图里做视觉节奏切换，
# 不想让整个详情页从头到尾一个颜色，看起来像没排过版。
_DARK_BG = (26, 26, 28)
_DARK_ACCENT = (196, 165, 116)  # 跟商品腰头logo的金棕色呼应
_DARK_TEXT = (235, 235, 232)
_LIGHT_BG = (250, 249, 247)
_LIGHT_TEXT = (40, 40, 40)


def _font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size)


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    """按像素宽度换行，中文没有天然分词，这里按字符累加宽度手动换行，
    不用 textwrap.wrap()（那个是按单词数量猜的，中文场景下不准）。
    """
    lines: list[str] = []
    current = ""
    for ch in text:
        trial = current + ch
        width = draw.textbbox((0, 0), trial, font=font)[2]
        if width > max_width and current:
            lines.append(current)
            current = ch
        else:
            current = trial
    if current:
        lines.append(current)
    return lines


def render_selling_points_card(bullet_points: list[str], out_path: str) -> str:
    # 2026-08-12 按反馈去掉了"核心卖点"这种通用板块标题——真实详情页很少会这样给自己贴标签，
    # 读起来像模板生成的，很尴尬，直接让内容本身说话就够了。
    if not bullet_points:
        raise ValueError("bullet_points 为空，没有内容可以渲染卖点图")

    padding = 64
    bullet_font = _font(_FONT_REGULAR, 30)  # 字号往小调一点，配合加宽的卡片，让长一点的卖点也能单行放下
    line_height = 44
    bullet_gap = 40

    # 先用一个临时画布量出每条卖点要占几行，算出总高度，再建正式画布——
    # 不然高度写死的话，卖点少了留白难看，卖点多了直接被裁掉。
    probe = Image.new("RGB", (10, 10))
    probe_draw = ImageDraw.Draw(probe)
    max_text_width = _CARD_WIDTH - padding * 2 - 60  # 60是留给圆点icon的宽度
    wrapped_bullets = [_wrap_text(probe_draw, b, bullet_font, max_text_width) for b in bullet_points]

    content_height = sum(len(lines) * line_height + bullet_gap for lines in wrapped_bullets)
    height = padding * 2 + content_height

    img = Image.new("RGB", (_CARD_WIDTH, int(height)), _DARK_BG)
    draw = ImageDraw.Draw(img)

    y = padding
    for lines in wrapped_bullets:
        # 圆点icon纵向对齐第一行文字的中心
        dot_y = y + line_height // 2 - 6
        draw.ellipse([padding, dot_y, padding + 12, dot_y + 12], fill=_DARK_ACCENT)
        for i, line in enumerate(lines):
            draw.text((padding + 44, y + i * line_height), line, font=bullet_font, fill=_DARK_TEXT)
        y += len(lines) * line_height + bullet_gap

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    img.save(out_path)
    return out_path


def render_description_card(description: str, out_path: str) -> str:
    # 同上，去掉了"产品介绍"这个板块标题。
    if not description:
        raise ValueError("description 为空，没有内容可以渲染介绍图")

    padding = 64
    body_font = _font(_FONT_REGULAR, 30)
    line_height = 48
    paragraph_gap = 36  # 段落之间额外留白，视觉上相当于隔了一行空行，不是靠打真的空行字符撑出来的

    # copywriter.py 现在会要求LLM用 \n\n 分段——按空行切出自然段，每段单独换行排版，
    # 不是把整段description当成一长串字符无脑换行，那样读起来是一大块很挤的文字墙。
    paragraphs = [p.strip() for p in description.split("\n") if p.strip()]
    if not paragraphs:
        paragraphs = [description]

    probe = Image.new("RGB", (10, 10))
    probe_draw = ImageDraw.Draw(probe)
    max_text_width = _CARD_WIDTH - padding * 2
    wrapped_paragraphs = [_wrap_text(probe_draw, p, body_font, max_text_width) for p in paragraphs]

    content_height = sum(len(lines) * line_height for lines in wrapped_paragraphs)
    content_height += paragraph_gap * max(0, len(wrapped_paragraphs) - 1)
    height = padding * 2 + content_height

    img = Image.new("RGB", (_CARD_WIDTH, int(height)), _LIGHT_BG)
    draw = ImageDraw.Draw(img)

    y = padding
    for p_index, lines in enumerate(wrapped_paragraphs):
        for line in lines:
            draw.text((padding, y), line, font=body_font, fill=_LIGHT_TEXT)
            y += line_height
        if p_index < len(wrapped_paragraphs) - 1:
            y += paragraph_gap

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    img.save(out_path)
    return out_path
