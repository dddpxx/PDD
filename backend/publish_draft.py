"""人工审核 preview.html 后，把 publish_draft.json 填入商家后台并保存草稿。"""

import argparse
import json
import os

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

from pdd_agent.auth import load_playwright_cookies, new_stealth_context
from pdd_agent.merchant_publisher import fill_publish_form, open_publish_form, save_draft
from pdd_agent.store_publisher import PublishColorOption, PublishPlan


def _load_payload(path: str) -> tuple[str, list[str], PublishPlan]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    plan_data = data["plan"]
    plan_data["colors"] = [PublishColorOption(**color) for color in plan_data["colors"]]
    return data["title"], data["carousel_images"], PublishPlan(**plan_data)


def main() -> None:
    parser = argparse.ArgumentParser(description="把已审核的商品方案填入拼多多商家后台并保存草稿")
    parser.add_argument("payload", help="run_pipeline.py 生成的 publish_draft.json")
    parser.add_argument("category_search_term", help="类目搜索词，例如：男士平角裤")
    parser.add_argument("category_option_text", help="精确类目路径，例如：内衣裤 > 男士内裤 > 平角裤")
    parser.add_argument("--shipping-template", default="", help="需要选择的运费模板名称；留空则保留页面默认值")
    args = parser.parse_args()

    load_dotenv()
    state_path = os.environ.get("PDD_MERCHANT_STATE_PATH", "merchant_cookies.txt")
    title, images, plan = _load_payload(args.payload)
    cookies = load_playwright_cookies(state_path)

    with sync_playwright() as playwright:
        browser, context = new_stealth_context(playwright, cookies, headless=False)
        try:
            page = context.new_page()
            open_publish_form(page, args.category_search_term, args.category_option_text)
            failed = fill_publish_form(
                page,
                title=title,
                carousel_images=images,
                plan=plan,
                shipping_template=args.shipping_template,
            )
            if failed:
                raise RuntimeError(f"这些动态属性仍未填写，未保存草稿: {', '.join(failed)}")
            save_draft(page)
            print("商家后台草稿已保存；请人工复核后再点击“提交并上架”")
        finally:
            browser.close()


if __name__ == "__main__":
    main()
