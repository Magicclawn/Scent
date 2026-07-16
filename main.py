"""scent v2.9 — feedback-driven web fuzzer"""

import argparse
import asyncio
import os
import sys
import time
from urllib.parse import urlparse
from core.engine import Scanner
from utils.dict_loader import load_dict
from core.config import random_ua, BANNER
from utils.checkpoint import load_checkpoint, get_default_checkpoint_path
from utils.diff import render_diff


def load_url_file(path):
    urls = set()
    with open(path, "r", encoding="utf-8") as f:
        for line in f.readlines():
            if line.startswith("#") or not line.strip():
                continue
            urls.add(line.strip())
    return urls

def _batch_report_path(base_path, url):
    host = urlparse(url).hostname
    name, ext = os.path.splitext(base_path)
    return f"{name}_{host}{ext}"


async def scan_target(url, args, paths, headers, include_status, ssl):
    import argparse as _argparse

    target_args = _argparse.Namespace(**vars(args))
    target_args.url = url

    if args.report:
        target_args.report = _batch_report_path(args.report, url)

    checkpoint_path = get_default_checkpoint_path(url)

    start = time.time()
    scanner = Scanner(
        target_args, args.proxy, ssl, headers, include_status,
        paths, checkpoint_path=checkpoint_path,
    )

    try:
        await scanner.run()
        elapsed = time.time() - start
        return {"url": url, "cnt": scanner.cnt, "scanned": scanner.scanned,
                "elapsed": elapsed, "error": None}
    except Exception as e:
        elapsed = time.time() - start
        return {"url": url, "cnt": 0, "scanned": 0,
                "elapsed": elapsed, "error": str(e)}

def print_summary(results):
    """打印批量扫描汇总表"""
    if not results:
        return

    # 算 URL 列最大宽度
    max_url_len = max(len(r["url"]) for r in results)
    url_width = max(max_url_len, 4)  # 至少容下 "目标" 标题

    total_found = 0
    total_scanned = 0
    total_elapsed = 0

    print(f"\n{'=' * 80}")
    print(f"  {'目标':{url_width}}    {'发现':>6}  {'请求':>8}  {'耗时':>8}  状态")
    print(f"  {'─' * url_width}    {'─' * 6}  {'─' * 8}  {'─' * 8}  ────")

    for r in results:
        total_found += r["cnt"]
        total_scanned += r["scanned"]
        total_elapsed += r["elapsed"]

        if r["error"]:
            status = f"✗ {r['error']}"
        else:
            status = "✓"

        print(f"  {r['url']:{url_width}}    {r['cnt']:>6}  {r['scanned']:>8}  {r['elapsed']:>7.1f}s  {status}")

    print(f"  {'─' * url_width}    {'─' * 6}  {'─' * 8}  {'─' * 8}  ────")
    print(f"  {'合计':{url_width}}    {total_found:>6}  {total_scanned:>8}  {total_elapsed:>7.1f}s")
    print(f"{'=' * 80}\n")

async def run_batch(urls, args, paths, headers, include_status, ssl):
    total = len(urls)
    print(f"\n{'=' * 60}")
    print(f"  批量扫描: {total} 个目标 | 字典: {args.wordlist} | 并发: {args.concurrency}")
    print(f"{'=' * 60}")
    results = []
    for i ,url in enumerate(urls, 1):
        print(f"\n── 目标 [{i}/{total}]: {url} ──")
        result = await scan_target(url, args, paths, headers, include_status, ssl)
        results.append(result)

    print_summary(results)

def build_context(args):
    headers = {}
    if args.cookie:
        headers["Cookie"] = args.cookie
    if args.ua:
        headers["User-Agent"] = args.ua
    else:
        headers["User-Agent"] = random_ua()
    if args.header:
        for h in args.header:
            key, value = h.split(":", 1)
            headers[key.strip()] = value.strip()
    include_status = set()
    if args.include_status:
        include_status = set(int(code.strip()) for code in args.include_status.split(","))

    report_format = args.report_format
    ssl = False if args.ignore_ssl_errors else None

    return headers, include_status, ssl


async def run_diff_mode(args):
    """diff 模式：请求两个路径并对比响应体"""
    import aiohttp
    url = args.diff_url.rstrip("/")

    async with aiohttp.ClientSession() as session:
        headers = {"User-Agent": random_ua()}
        ssl = False if args.ignore_ssl_errors else None

        async def fetch(path, label):
            full = f"{url}/{path.lstrip('/')}"
            print(f"[*] 请求 {label}: {full}")
            try:
                async with session.get(full, headers=headers, timeout=args.timeout, ssl=ssl) as resp:
                    body = await resp.read()
                    print(f"[*] {label}: HTTP {resp.status}, {len(body)}B")
                    return body, resp.status
            except Exception as e:
                print(f"[-] {label} 请求失败: {e}")
                return b"", 0

        body_a, status_a = await fetch(args.diff_a, "A")
        body_b, status_b = await fetch(args.diff_b, "B")

    label_a = f"A: /{args.diff_a} (HTTP {status_a}, {len(body_a)}B)"
    label_b = f"B: /{args.diff_b} (HTTP {status_b}, {len(body_b)}B)"

    print(f"\n{'=' * 60}")
    print(f"  Diff: /{args.diff_a}  ←→  /{args.diff_b}")
    print(f"{'=' * 60}\n")

    diff_output = render_diff(body_a, body_b, label_a, label_b)
    print(diff_output)


def main():
    # 1. 解析命令行参数
    parser = argparse.ArgumentParser(description="scent v2.9 — feedback-driven web fuzzer")
    parser.add_argument("-u", "--url", help="目标URL，如 http://example.com")
    parser.add_argument("-w", "--wordlist", default="dict/quick.txt", help="字典文件路径（默认 dict/quick.txt）")
    parser.add_argument("-c", "--concurrency", type=int, default=20, help="并发数（默认 20）")
    parser.add_argument("-T", "--timeout", type=int, default=5, help="请求超时（秒）")
    parser.add_argument("-x", "--exclude-status", help="排除的状态码，逗号分隔，如404,301")
    parser.add_argument("-r", "--recursive", action="store_true", help="开启递归扫描")
    parser.add_argument("-R", "--depth", type=int, default=3, help= "最大递归深度")
    parser.add_argument("-e", "--extension", help="扩展名爆破")
    parser.add_argument("-i", "--include-status", help="白名单模式")
    parser.add_argument("--recursion-status", help="触发递归的状态码，默认200，301，302")
    parser.add_argument("--max-size", type=int, help="响应包最大尺寸")
    parser.add_argument("--min-size", type=int, help="响应包最小尺寸")
    # ── 高级 filter 参数 ──
    parser.add_argument("--filter-sizes", help="排除指定大小的响应，如 100-200,500-600")
    parser.add_argument("--filter-status", help="排除指定状态码，如 404,301")
    parser.add_argument("--filter-time", help="排除指定响应时间(ms)，如 >500,<100")
    parser.add_argument("--filter-text", help="排除包含指定文本的响应，逗号分隔")
    parser.add_argument("--filter-regex", help="排除匹配正则的响应")
    parser.add_argument("--filter-headers", help="排除响应头包含指定文本，逗号分隔")
    parser.add_argument("--filter-redirect", help="排除重定向到指定路径的响应")
    parser.add_argument("--filter-mode", default="or", choices=["and", "or"], help="filter 匹配模式: and=全部满足 or=任一满足 (默认or)")

    parser.add_argument("--match-status", help="只报告指定状态码，如 200,403")
    parser.add_argument("--match-sizes", help="只报告指定大小的响应，如 >1000,500-600")
    parser.add_argument("--match-time", help="只报告指定响应时间(ms)，如 <100")
    parser.add_argument("--match-text", help="只报告包含指定文本的响应，逗号分隔")
    parser.add_argument("--match-regex", help="只报告匹配正则的响应")
    parser.add_argument("--match-headers", help="只报告响应头包含指定文本，逗号分隔")
    parser.add_argument("--matcher-mode", default="or", choices=["and", "or"], help="match 匹配模式: and=全部满足 or=任一满足 (默认or)")

    parser.add_argument("--header", action="append", help="自定义请求头")
    parser.add_argument("--ua", help="自定义 User-Agent")
    parser.add_argument("--proxy", help="自定义代理 支持HTTP/HTTPS/SOCKS")
    parser.add_argument("--cookie", help="支持认证场景")
    parser.add_argument("--ignore-ssl-errors", action="store_true", help="跳过证书验证")
    parser.add_argument("--quiet", action="store_true", help="静默模式")
    parser.add_argument("--retries", type=int, default=3, help="请求重试次数")
    parser.add_argument("--crawl", action="store_true", help="爬取模式")
    parser.add_argument("--no-wildcard", action="store_true", help="关闭通配符检测")
    parser.add_argument("--report", help="输出报告路径")
    parser.add_argument("--report-format", default="txt", choices=["json", "csv", "html", "txt"], help="报告格式(默认：txt)")
    parser.add_argument("--method", default="GET", choices=["GET", "POST", "PUT", "HEAD", "DELETE", "PATCH", "OPTIONS"], help="请求方法")
    parser.add_argument("--data", help="请求body")
    parser.add_argument("--delay", type=float, default=0, help="延迟请求")
    parser.add_argument("--follow-redirect", action="store_true", help="跟随重定向")
    parser.add_argument("--resume", help="从 checkpoint 文件恢复扫描")
    parser.add_argument("--checkpoint", help="自定义 checkpoint 保存路径（默认 .checkpoint_<host>.json）")
    parser.add_argument("--diff-url", help="diff 模式：目标 URL（如 http://example.com）")
    parser.add_argument("--diff-a", help="diff 模式：路径 A")
    parser.add_argument("--diff-b", help="diff 模式：路径 B")
    parser.add_argument("--show-diff", action="store_true", help="扫描中 wildcard 过滤时显示响应体差异")
    parser.add_argument("--adaptive", action="store_true", help="速率自适应")
    parser.add_argument("--pattern-learn", action="store_true", help="模式学习：扫描中生成变体候选")
    parser.add_argument("--url-file", help="url文件路径")
    args = parser.parse_args()

    # ── URL 互斥校验 ───────────────────────────────────────
    if not args.url and not args.url_file:
        parser.error("必须指定 -u/--url 或 --url-file")
    if args.url and args.url_file:
        parser.error("-u/--url 和 --url-file 不能同时使用")

    if args.url_file:
        urls = load_url_file(args.url_file)
    else:
        urls = {args.url}

    # ── Diff 模式（略过扫描）────────────────────────────────
    if args.diff_url and args.diff_a and args.diff_b:
        asyncio.run(run_diff_mode(args))
        return

    exts = None
    if args.extension:
        exts = [e.strip() for e in args.extension.split(",")]
    paths = load_dict(args.wordlist, exts)

    # ── 检查点恢复 ──
    resume_checkpoint = None
    checkpoint_path = args.checkpoint

    if len(urls) == 1:
        url = list(urls)[0]
        args.url = url
        resume_checkpoint = None
        checkpoint_path = args.checkpoint

        if args.resume:
            resume_checkpoint = load_checkpoint(args.resume)
            # 校验 URL 一致
            if resume_checkpoint["url"] != args.url:
                print(f"[-] checkpoint URL ({resume_checkpoint['url']}) 与当前 URL ({args.url}) 不一致，拒绝恢复")
                sys.exit(1)
            # 校验 wordlist hash
            from utils.checkpoint import _hash_wordlist
            current_hash = _hash_wordlist(paths)
            saved_hash = resume_checkpoint.get("wordlist_hash")
            if saved_hash and saved_hash != current_hash:
                print(f"[!] 警告: 字典内容与 checkpoint 时不一致，结果可能不完整")
            # 自动使用 checkpoint 中保存的路径
            if not checkpoint_path:
                checkpoint_path = args.resume
            if not args.quiet:
                previously_scanned = resume_checkpoint.get("scanned", 0)
                previously_found = resume_checkpoint.get("cnt", 0)
                print(f"[*] 从 checkpoint 恢复: 已扫描 {previously_scanned} 条，发现 {previously_found} 个路径")
                print(f"[*] 跳过已扫描的 {len(resume_checkpoint.get('scanned_paths', []))} 条路径，继续扫描...\n")
        elif not checkpoint_path:
            checkpoint_path = get_default_checkpoint_path(args.url)

        if not args.quiet:
            print(BANNER)
            print(f"[*] 目标: {args.url}")
            print(f"[*] 字典: {args.wordlist}")
            print(f"[*] 并发数：{args.concurrency}")
            print(f"[*] 开始扫描...\n")

        headers, include_status, ssl = build_context(args)
        asyncio.run(Scanner(args,
                            args.proxy,
                            ssl,
                            headers,
                            include_status,
                            paths,
                            resume_checkpoint=resume_checkpoint,
                            checkpoint_path=checkpoint_path,
                            ).run())
    else:
        if args.resume:
            print("[-] --resume 不支持批量扫描")
            sys.exit(1)
        if not args.quiet:
            print(f"[*] 加载 {len(urls)} 个目标")
        headers, include_status, ssl = build_context(args)
        asyncio.run(run_batch(urls, args, paths, headers, include_status, ssl))
        

if __name__ == "__main__":
    main()
