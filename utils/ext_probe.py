"""扩展名探测：试探路径判断目标支持哪些扩展名"""
import asyncio
import aiohttp


# 探测用路径：选高价值、短路径，覆盖不同目录层级
PROBE_PATHS = [
    "index", "admin/login", "login", "api/v1/info",
    "readme", "home", "test", "info", "status",
    "config/app", "backup/db",
]


async def probe_extensions(session, url, extensions, headers, timeout, concurrency):
    """并发探测每个扩展名在所有探测路径上的响应，返回命中的扩展名集合。

    命中的扩展名会被优先扫描；未命中的仍会扫描但排到后面——不丢不漏。
    """
    hit = set()
    sem = asyncio.Semaphore(concurrency)

    async def probe_one(ext, path):
        target = f"{url.rstrip('/')}/{path}.{ext}"
        try:
            async with sem:
                async with session.get(
                    target, headers=headers, timeout=timeout,
                    allow_redirects=False,
                ) as resp:
                    # 非 404 且非 wildcard 占位符即视为命中
                    if resp.status != 404:
                        await resp.read()  # consume
                        return ext
        except (aiohttp.ClientError, asyncio.TimeoutError):
            pass
        return None

    tasks = []
    for ext in extensions:
        for path in PROBE_PATHS:
            tasks.append(probe_one(ext, path))

    results = await asyncio.gather(*tasks)
    for ext in results:
        if ext is not None:
            hit.add(ext)

    return hit
