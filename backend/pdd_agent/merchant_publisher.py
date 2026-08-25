"""Module 07 - 用Playwright操作商家后台真实网页完成发布（对应DM.md §16的路线转向）。

商品属性区域是自绘组件库（不是标准<select>/ARIA combobox，文字/role定位都不稳定，见DM.md §16
和这次探索过程），但每个属性字段的容器有稳定的 `id="basic.propertys.N.value"`，这是这个模块
定位表单元素的主要手段。**N不能硬编码**——选中某些值（比如"面料俗称=棉"）会让表单联动插入新的
字段（比如"成分含量"），后面字段的N会跟着变，所以每次都要按label文字动态查找容器，不能假设固定index。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from .store_publisher import PublishPlan

if TYPE_CHECKING:
    from playwright.sync_api import Page
else:
    Page = Any

_DROPDOWN_TRIGGER = ".ST_selectValueSingle_5-188-0"
_DROPDOWN_PANEL = ".ST_dropdownPanel_5-188-0"


def open_publish_form(page: Page, category_search_term: str, category_option_text: str) -> None:
    """从"发布新商品"分类选择页开始，搜类目、选中、确认，一路走到商品编辑表单页。
    这是已经反复验证过很多次的固定流程，抽成函数避免每个探索脚本都重新贴一遍。"""
    page.goto("https://mms.pinduoduo.com/goods/category", wait_until="load", timeout=30000)
    page.wait_for_timeout(2000)
    search_box = page.locator("input[placeholder*='搜索分类']")
    search_box.click(force=True)
    search_box.type(category_search_term, delay=120)
    page.wait_for_timeout(1500)
    page.click(f"text={category_option_text}")
    page.wait_for_timeout(1000)
    page.click("text=确认发布该类商品")
    page.wait_for_timeout(2500)
    try:
        page.click("text=知道了", timeout=2000)  # "热区图片组件上线了"这类运营弹窗，出现就关掉，不出现也不报错
    except Exception:
        pass
    page.wait_for_timeout(1000)


def fill_title(page: Page, title: str) -> None:
    title_input = page.locator("input[placeholder*='商品标题组成']")
    title_input.click(force=True)
    title_input.fill(title)
    page.wait_for_timeout(500)


def upload_carousel_images(page: Page, image_paths: list[str]) -> None:
    """商品轮播图上传。之前只验证过传一张图成功，这里传多张是否会追加而不是覆盖、
    每张之间要不要额外等待，还没有拿真实页面测过，第一次跑这个函数要盯着看结果对不对。"""
    upload_input = page.locator("input[type='file']").first
    for path in image_paths:
        upload_input.set_input_files(path)
        page.wait_for_timeout(1500)  # 给后端一点处理时间再传下一张，具体要不要这么久没验证过，先保守


def _find_property_container(page: Page, label_substring: str):
    """按label文字动态查找属性字段容器，不依赖固定的index（原因见模块docstring）。"""
    items = page.locator('[id^="basic.propertys."]')
    count = items.count()
    for i in range(count):
        item = items.nth(i)
        label = item.locator("label").first
        if label.count() and label_substring in label.inner_text():
            return item
    return None


def select_property_dropdown(page: Page, label_substring: str, option_text: str) -> bool:
    """给"商品属性"区域里某个下拉框选中一个值。返回True表示找到字段并点了选项，
    False表示这次没找到这个字段（比如"成分含量"这种联动字段，选之前的字段之前根本不存在）。"""
    container = _find_property_container(page, label_substring)
    if container is None:
        return False
    trigger = container.locator(_DROPDOWN_TRIGGER).first
    trigger.click(timeout=5000)
    page.wait_for_timeout(600)
    panel = page.locator(_DROPDOWN_PANEL).last
    option = panel.get_by_text(option_text, exact=True).first
    option.click(timeout=5000)
    page.wait_for_timeout(600)
    return True


def fill_attributes(page: Page, attributes: dict[str, str]) -> list[str]:
    """按顺序把 attributes 字典（label子串 -> 选项文字）填进"商品属性"区域，
    返回没能成功填上的字段列表（比如联动字段在填了前置字段之前还不存在，第一轮找不到）。

    attributes 的key顺序很重要——调用方传入时要把"面料俗称"这种会触发联动字段的排在前面，
    这个函数本身不负责猜哪个字段会联动出新字段。
    """
    failed: list[str] = []
    for label_substring, option_text in attributes.items():
        if not option_text:
            failed.append(label_substring)
            continue
        ok = select_property_dropdown(page, label_substring, option_text)
        if not ok:
            failed.append(label_substring)
    return failed


class HumanInterventionRequired(RuntimeError):
    pass


def _stop_on_verification(page: Page) -> None:
    matches = page.get_by_text(re.compile("滑块|验证码|异常验证"))
    if any(matches.nth(i).is_visible() for i in range(matches.count())):
        raise HumanInterventionRequired("页面出现验证码或异常验证，已停止自动化，请人工处理后重试")


def _first(page: Page, selectors: tuple[str, ...]):
    for selector in selectors:
        locator = page.locator(selector)
        if locator.count():
            return locator.first
    raise RuntimeError(f"页面结构已变化，找不到控件: {selectors}")


def fill_color_options(page: Page, names: list[str]) -> None:
    field = _first(
        page,
        (
            "input[placeholder*='添加颜色分类']",
            "input[placeholder*='颜色分类主色']",
            "input[placeholder*='添加规格值']",
        ),
    )
    for name in names:
        field.fill(name)
        field.press("Enter")
        page.wait_for_timeout(300)


def select_sizes(page: Page, sizes: list[str]) -> None:
    page.get_by_text("中国码", exact=True).last.click()
    for size in sizes:
        page.get_by_text(size, exact=True).last.click()
    page.wait_for_timeout(500)


def _fill_after_text(page: Page, label: str, value: str) -> None:
    locator = page.get_by_text(label, exact=True).last.locator("xpath=following::input[1]")
    if not locator.count():
        raise RuntimeError(f"页面结构已变化，找不到“{label}”后的输入框")
    locator.fill(value)


def fill_inventory_and_prices(page: Page, plan: PublishPlan) -> None:
    _fill_after_text(page, "库存", str(plan.stock))
    _fill_after_text(page, "拼单价", f"{plan.group_price:.2f}")
    _fill_after_text(page, "单买价", f"{plan.single_price:.2f}")
    _fill_after_text(page, "商品参考价", f"{plan.reference_price:.2f}")

    discount = page.get_by_text("满件折扣", exact=True).last
    row = discount.locator("xpath=ancestor::div[.//input][1]")
    inputs = row.locator("input")
    rate = f"{plan.bulk_discount_rate * 10:g}"
    if inputs.count() >= 2:
        inputs.nth(0).fill(str(plan.bulk_discount_quantity))
        inputs.nth(1).fill(rate)
    elif inputs.count() == 1:
        inputs.first.fill(rate)


def fill_shipping_and_services(page: Page, plan: PublishPlan, shipping_template: str = "") -> None:
    page.get_by_text(f"{plan.shipping_promise}内发货", exact=False).last.click()
    no_reason = page.get_by_text("7天无理由退货", exact=False).last
    checkbox = no_reason.locator("xpath=preceding::input[@type='checkbox'][1]")
    if checkbox.count() and checkbox.is_checked() != plan.no_reason_return:
        no_reason.click()
    if shipping_template:
        row = page.get_by_text("运费模板", exact=False).last
        row.locator("xpath=following::*[contains(@class,'select')][1]").click()
        page.get_by_text(shipping_template, exact=True).last.click()


def fill_publish_form(
    page: Page,
    *,
    title: str,
    carousel_images: list[str],
    plan: PublishPlan,
    shipping_template: str = "",
) -> list[str]:
    """填完整张表单但不提交上架；返回两轮后仍未能填写的动态属性。"""
    _stop_on_verification(page)
    fill_title(page, title)
    upload_carousel_images(page, carousel_images)
    page.wait_for_timeout(6000)  # 等平台的图片智能属性回填结束，避免覆盖我们的值
    failed = fill_attributes(page, plan.attributes)
    if failed:
        failed = fill_attributes(page, {key: plan.attributes[key] for key in failed})
    fill_color_options(page, [color.name for color in plan.colors])
    select_sizes(page, plan.sizes)
    fill_inventory_and_prices(page, plan)
    fill_shipping_and_services(page, plan, shipping_template)
    _stop_on_verification(page)
    return failed


def save_draft(page: Page) -> None:
    """保存草稿是自动化边界；“提交并上架”仍需人工审核后点击。"""
    _stop_on_verification(page)
    page.get_by_text("保存草稿", exact=True).last.click()
    page.wait_for_timeout(1500)
    _stop_on_verification(page)
