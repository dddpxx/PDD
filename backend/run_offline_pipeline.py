"""Generate review-only artifacts from the rights-cleared local fixture."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

from pdd_agent.detail_builder import build_detail_page
from pdd_agent.importer import parse_product
from pdd_agent.models import Copy, Keyword
from pdd_agent.store_publisher import build_publish_plan
from pdd_agent.typo_fix import fix_known_typos_in_text

FIXTURE_PATH = Path(__file__).with_name("fixtures") / "offline_product.json"


def _relative(path: str, output_dir: Path) -> str:
    return Path(os.path.relpath(path, output_dir)).as_posix()


def run_offline_pipeline(output_dir: str | Path) -> tuple[Path, Path]:
    output_dir = Path(output_dir)
    fixture_path = FIXTURE_PATH
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    fixture_info = fixture.get("fixture", {})
    if fixture_info.get("sanitized") is not True or fixture_info.get("rights") != "CC0-1.0":
        raise ValueError("fixture must be sanitized and rights-cleared as CC0-1.0")

    print("[1/4] parse fixed fixture")
    product = parse_product(fixture["state"], fixture["source_url"], fixture["goods_id"])

    print("[2/4] apply reviewed text and image decisions")
    fixture_dir = fixture_path.parent.resolve()
    assets = fixture["assets"]
    for image in product.images:
        asset = assets[image.url]
        local_path = (fixture_dir / asset["path"]).resolve()
        local_path.relative_to(fixture_dir)
        if not local_path.is_file():
            raise FileNotFoundError(local_path)
        image.local_path = str(local_path)
        image.type = asset["type"]
        image.tag = asset["tag"]

    copy_data = fixture["copy"]
    copy = Copy(
        title=fix_known_typos_in_text(copy_data["title"]),
        bullet_points=[fix_known_typos_in_text(item) for item in copy_data["bullet_points"]],
        description=fix_known_typos_in_text(copy_data["description"]),
    )
    keywords = [Keyword(**item) for item in fixture["keywords"]]

    print("[3/4] build local preview")
    output_dir.mkdir(parents=True, exist_ok=True)
    kept_images = [image for image in product.images if image.tag == "KEEP" and image.type in ("product", "text_info")]
    preview = build_detail_page(product, copy, keywords, [], str(output_dir))
    copied_by_url = dict(zip((image.url for image in kept_images), preview.ordered_images))
    for sku in product.skus:
        sku.thumb_url = copied_by_url.get(sku.thumb_url, sku.thumb_url)

    print("[4/4] build local publish plan")
    plan = asdict(build_publish_plan(product))
    for color in plan["colors"]:
        color["thumb_url"] = _relative(color["thumb_url"], output_dir)
    draft_path = output_dir / "publish_draft.json"
    draft_path.write_text(
        json.dumps(
            {
                "title": copy.title,
                "carousel_images": [_relative(path, output_dir) for path in preview.carousel_images],
                "plan": plan,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return output_dir / "preview.html", draft_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="output/jing-30", help="local output directory")
    args, unsupported = parser.parse_known_args()
    if unsupported:
        print(f"[offline] failed: unsupported arguments: {' '.join(unsupported)}", file=sys.stderr)
        return 1
    try:
        preview_path, draft_path = run_offline_pipeline(args.output)
    except Exception as exc:
        print(f"[offline] failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(f"[offline] ok: {preview_path}")
    print(f"[offline] ok: {draft_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
