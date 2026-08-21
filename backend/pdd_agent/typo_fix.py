"""已知错别字 - 文案文本兜底替换。

原图上的错字（比如"不勒退"应该是"不勒腿"）不只会留在图片本身里——Module 02读图提取facts/
selling_points时会把这类文字原样抄进去，Module 04写文案时又会引用这些facts，实测出现过
"同时带有不勒退的特点"这种把错字当成正经产品特性写进自己生成文案的情况。

2026-08-13：原本这里还有一套"在原图错字上盖圆角矩形补丁、写上修正文字"的图片级修复机制
（配合AI判断/OCR转录+代码里精确字符串匹配 KNOWN_TYPO_FIXES 定位错字位置），但生成的补丁
视觉效果不自然，用户明确要求取消这套图片涂改机制，改成自己手动处理原图里的错字。
文案文本这一层的兜底替换还留着——这个是纯文本替换、不涉及图片二次加工，不在用户反馈的问题范围内。
"""

from __future__ import annotations

# 已经人工确认过的错别字修正表，不依赖AI每次重新判断对错。发现新的错别字就往这张表里加一条——
# 这是个会随着用得越多越完善的表，不追求一次性覆盖所有可能的错字。
KNOWN_TYPO_FIXES: dict[str, str] = {
    "不勒退": "不勒腿",
}


def fix_known_typos_in_text(text: str) -> str:
    """对 Module 02/04 生成的文本字段（facts.features / selling_points / title / bullet_points /
    description）做一次已知错字替换，避免原图上的错字被当成正经产品特性写进自己的文案里。"""
    for wrong, corrected in KNOWN_TYPO_FIXES.items():
        text = text.replace(wrong, corrected)
    return text
