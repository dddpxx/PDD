"""用merchant_publisher.py里已经整合的函数测一遍：分类→标题→多图上传→属性。用完即删。"""

import glob

from playwright.sync_api import sync_playwright

from pdd_agent.auth import load_playwright_cookies, new_stealth_context
from pdd_agent.merchant_publisher import fill_attributes, fill_title, open_publish_form, upload_carousel_images
from pdd_agent.store_publisher import _FIXED_ATTRIBUTES

cookies = load_playwright_cookies("merchant_cookies.txt")
images = sorted(glob.glob("output/981833693052/scenes/*.png"))
print(f"准备上传{len(images)}张图")

with sync_playwright() as p:
    browser, context = new_stealth_context(p, cookies, headless=False)
    page = context.new_page()

    open_publish_form(page, "男士平角裤", "男士内裤 > 平角裤")
    fill_title(page, "男士夏季平角内裤 双C囊袋 透气凉感")
    upload_carousel_images(page, images)
    # 实测上传图片会触发拼多多自己的"根据图片智能推荐属性"异步渲染，如果紧接着就填属性，
    # 填完之后这个异步渲染才落地，会把已经填好的值覆盖掉——这里多等一会，等它先稳定下来。
    page.wait_for_timeout(6000)
    page.screenshot(path="_explore_after_images.png", full_page=True)

    failed = fill_attributes(page, _FIXED_ATTRIBUTES)
    if failed:
        failed = fill_attributes(page, {k: _FIXED_ATTRIBUTES[k] for k in failed})
    print("最终没填上的属性:", failed)

    page.screenshot(path="_explore_final.png", full_page=True)
    browser.close()
