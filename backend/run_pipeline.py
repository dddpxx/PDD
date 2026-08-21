import sys

from dotenv import load_dotenv

load_dotenv()

from pdd_agent.config import load_settings
from pdd_agent.pipeline import run_pipeline


def main() -> None:
    if len(sys.argv) != 2:
        print("用法: python run_pipeline.py <拼多多商品链接>")
        sys.exit(1)

    url = sys.argv[1]
    settings = load_settings()
    run_pipeline(url, settings)


if __name__ == "__main__":
    main()
