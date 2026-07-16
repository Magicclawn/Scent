"""异步HTTP请求 + 指数退避重试"""

import time
import aiohttp
import asyncio
import random

# ─── 需要重试的异常 ─────────────────────────────────────────

RETRYABLE_EXCEPTIONS = (
    aiohttp.ClientConnectionError,
    aiohttp.ServerTimeoutError,
    asyncio.TimeoutError,
)


def _should_retry(exception, attempt, retries):
    """判断是否应该重试"""
    if attempt >= retries - 1:
        return False
    return isinstance(exception, RETRYABLE_EXCEPTIONS)


def _backoff(attempt, base=0.5, cap=8.0):
    """指数退避 + 随机抖动，返回等待秒数

    attempt=0: ~0.5s
    attempt=1: ~1.0s
    attempt=2: ~2.0s
    """
    delay = min(base * (2 ** attempt), cap)
    jitter = random.uniform(0, delay * 0.3)
    return delay + jitter

async def scan_async(session, url, path, headers, method, proxy, ssl=False, follow_redirect=False, data=None, timeout=5, retries=3):
    redirect_path = ""
    content_type = ""
    start = time.time()
    target = f"{url.rstrip('/')}/{path.lstrip('/')}"
    for attempt in range(retries):
        try:
            async with session.request(
                url=target, method=method, headers=headers,
                data=data, proxy=proxy, ssl=ssl,
                timeout=timeout, allow_redirects=follow_redirect,
            ) as resp:
                body = await resp.read()
                elapsed = time.time() - start
                if resp.status in (301, 302):
                    redirect_path = resp.headers.get("Location", "")
                return path, resp.status, redirect_path, body, resp.content_type, elapsed, dict(resp.headers)
        except RETRYABLE_EXCEPTIONS:
            if attempt == retries - 1:
                elapsed = time.time() - start
                return path, None, redirect_path, b"", "", elapsed, {}
            await asyncio.sleep(_backoff(attempt))
        except aiohttp.ClientError:
            # 非网络错误（如 InvalidURL）不重试
            elapsed = time.time() - start
            return path, None, redirect_path, b"", "", elapsed, {}
