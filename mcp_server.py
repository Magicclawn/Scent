"""scent MCP Server — 通过 MCP 协议暴露目录扫描能力给 agent"""
import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from utils.dict_loader import load_dict
from core.config import random_ua
from core.engine import Scanner


# ─── 工具定义 ──────────────────────────────────────────────

TOOLS = [
    Tool(
        name="run_scan",
        description="Run directory scan against a target URL with a wordlist",
        inputSchema={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Target URL, e.g. http://example.com"},
                "wordlist": {"type": "string", "description": "Path to wordlist file, or name of built-in wordlist (common, php, api, backup, dicc)"},
                "method": {"type": "string", "default": "GET", "enum": ["GET", "POST", "PUT", "HEAD", "DELETE", "PATCH", "OPTIONS"]},
                "concurrency": {"type": "integer", "default": 50},
                "extensions": {"type": "string", "description": "Comma-separated extensions, e.g. php,asp,jsp"},
                "recursive": {"type": "boolean", "default": False},
                "depth": {"type": "integer", "default": 3},
                "no_wildcard": {"type": "boolean", "default": False, "description": "Disable wildcard detection"},
                "delay": {"type": "number", "default": 0, "description": "Delay between requests in seconds"},
            },
            "required": ["url", "wordlist"],
        },
    ),
    Tool(
        name="list_wordlists",
        description="List built-in and available wordlist files from dirsearch db",
        inputSchema={"type": "object", "properties": {}, "required": []},
    ),
]


# ─── 字典解析 ──────────────────────────────────────────────

BUILTIN_WORDLISTS = {
    "common": "wordlist.txt",
}


def resolve_wordlist(name):
    """解析字典名称 → 文件路径"""
    me = os.path.dirname(os.path.abspath(__file__))

    if name in BUILTIN_WORDLISTS:
        return os.path.join(me, BUILTIN_WORDLISTS[name])

    # 搜索 dirsearch db 目录
    ddb = os.path.join(me, "..", "dirsearch", "dirsearch-master", "dirsearch-master", "db")
    if os.path.isdir(ddb):
        # 直接匹配
        for fname in os.listdir(ddb):
            if fname == name + ".txt" or fname == name:
                return os.path.join(ddb, fname)
        # 递归搜索
        for root, _dirs, files in os.walk(ddb):
            for f in files:
                if f == name + ".txt" or f == name:
                    return os.path.join(root, f)

    # 兜底：原样返回（可能是绝对路径）
    return name


def list_available_wordlists():
    """列出所有可用字典"""
    entries = [("common", "内置测试字典")]
    ddb = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "..", "dirsearch", "dirsearch-master", "dirsearch-master", "db")
    if os.path.isdir(ddb):
        for root, _dirs, files in os.walk(ddb):
            for f in sorted(files):
                if f.endswith(".txt"):
                    name = f[:-4] if f.endswith(".txt") else f
                    rel = os.path.relpath(os.path.join(root, f), ddb)
                    entries.append((name, rel))
    return entries


# ─── MCP Server ────────────────────────────────────────────

app = Server("scent")


@app.list_tools()
async def list_tools():
    return TOOLS


@app.call_tool()
async def call_tool(name: str, arguments: dict):
    if name == "list_wordlists":
        entries = list_available_wordlists()
        lines = [f"{e[0]:<25} {e[1]}" for e in entries]
        return [TextContent(type="text", text=f"{len(entries)} 个可用字典:\n" + "\n".join(lines))]

    elif name == "run_scan":
        wordlist_path = resolve_wordlist(arguments["wordlist"])

        exts = None
        if arguments.get("extensions"):
            exts = [e.strip() for e in arguments["extensions"].split(",")]

        paths = load_dict(wordlist_path, exts)

        args = argparse.Namespace(
            url=arguments["url"],
            method=arguments.get("method", "GET"),
            concurrency=arguments.get("concurrency", 50),
            timeout=5,
            extension=arguments.get("extensions"),
            recursive=arguments.get("recursive", False),
            depth=arguments.get("depth", 3),
            exclude_status=None,
            include_status=None,
            max_size=None,
            min_size=None,
            header=None,
            ua=None,
            proxy=None,
            cookie=None,
            ignore_ssl_errors=False,
            quiet=True,
            retries=3,
            crawl=False,
            no_wildcard=arguments.get("no_wildcard", False),
            report=None,
            report_format="txt",
            data=None,
            delay=arguments.get("delay", 0),
            follow_redirect=False,
            recursion_status=None,
        )

        headers = {"User-Agent": random_ua()}
        ssl = None
        proxy = None
        include_status = set()

        scanner = Scanner(args, proxy, ssl, headers, include_status, paths)

        # 捕获扫描输出
        captured = []

        class _Capture:
            def __init__(self):
                self.lines = []
            def write(self, txt):
                self.lines.append(txt)
            def flush(self):
                pass
            def isatty(self):
                return False

        cap = _Capture()
        old_stdout = sys.stdout
        sys.stdout = cap

        try:
            await scanner.run()
        finally:
            sys.stdout = old_stdout

        # 提取发现行
        results = []
        for line in cap.lines:
            s = line.strip()
            if s and ("发现" in s or "[+]" in s):
                results.append(s)

        return [TextContent(type="text", text=
            f"target: {arguments['url']}\n"
            f"wordlist: {arguments['wordlist']} ({len(paths)} paths)\n"
            f"method: {arguments.get('method', 'GET')}\n"
            f"found: {scanner.cnt}  scanned: {scanner.scanned}\n"
            + "\n".join(results)
        )]

    raise ValueError(f"Unknown tool: {name}")


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
