import time
from functools import lru_cache
from typing import Callable, TypeVar

from openai import APIConnectionError, InternalServerError, OpenAI, RateLimitError

from .config import Settings

T = TypeVar("T")


@lru_cache(maxsize=4)
def get_client(api_key: str, base_url: str | None) -> OpenAI:
    return OpenAI(api_key=api_key, base_url=base_url, max_retries=2)


def text_client(settings: Settings) -> OpenAI:
    return get_client(settings.text_api_key, settings.text_base_url)


def image_client(settings: Settings) -> OpenAI:
    return get_client(settings.image_api_key, settings.image_base_url)


def call_with_backoff(fn: Callable[[], T], *, retries: int = 5, base_delay: float = 6.0) -> T:
    """sublyx这类中转账号实测并发/频率额度比官方API紧很多，pipeline里几个文本调用是严格顺序发的、
    没有真并发，还是会连续撞到 429 Concurrency limit exceeded（偶尔还有连接被服务端直接断开，
    偶尔还有502 Upstream service temporarily unavailable这种上游服务暂时不可用）。
    SDK自带的重试退避太短，扛不住这种限流窗口，这里用更长、更明确的退避时间手动重试，
    每次重试都打印出来，免得看起来像卡死。"""
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            return fn()
        except (RateLimitError, APIConnectionError, InternalServerError) as e:
            last_error = e
            if attempt == retries:
                break
            delay = base_delay * (attempt + 1)
            print(f"      接口限流/连接问题，{delay:.0f}秒后重试（第{attempt + 1}/{retries}次）：{e}")
            time.sleep(delay)
    assert last_error is not None
    raise last_error
