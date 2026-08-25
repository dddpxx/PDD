import os

from .importer import MOBILE_HEADERS


def download_file(url: str, dest_path: str) -> str:
    import requests

    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    resp = requests.get(url, headers=MOBILE_HEADERS, timeout=20)
    resp.raise_for_status()
    with open(dest_path, "wb") as f:
        f.write(resp.content)
    return dest_path
