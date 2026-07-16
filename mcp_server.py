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


TOOLS = [
    Tool(
        name="run_scan",
        description="扫描目标URL，发现隐藏目录和文件",
        inputSchema={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "目标URL，例如 http://example.com"},
                "wordlist": {"type": "string", "description": "字典名称 (quick/standard/full) 或文件路径"},
                "concurrency": {"type": "integer", "default": 20},
                "extensions": {"type": "string", "description": "逗号分隔的扩展名，例如 php,html"},
                "recursive": {"type": "boolean", "default": False},
                "depth": {"type": "integer", "default": 3},
                "delay": {"type": "number", "default": 0, "description": "请求间隔（秒）"},
            },
            "required": ["url"],
        },
    ),
    Tool(
        name="list_wordlists",
        description="列出可用的内置字典",
        inputSchema={"type": "object", "properties": {}, "required": []},
    ),
]


BUILTIN_WORDLISTS = {
    "quick": "dict/quick.txt",
    "standard": "dict/standard.txt",
    "full": "dict/full.txt",
}


def resolve_wordlist(name):
    me = os.path.dirname(os.path.abspath(__file__))

    if name in BUILTIN_WORDLISTS:
        return os.path.join(me, BUILTIN_WORDLISTS[name])

    if os.path.exists(name):
        return name

    return os.path.join(me, "dict", f"{name}.txt")


def list_available_wordlists():
    me = os.path.dirname(os.path.abspath(__file__))
    entries = []
    for name, rel in BUILTIN_WORDLISTS.items():
        path = os.path.join(me, rel)
        if os.path.exists(path):
            lines = sum(1 for _ in open(path, encoding="utf-8", errors="ignore"))
            entries.append((name, f"{lines:,} 条路径"))
    return entries


app = Server("scent")


@app.list_tools()
async def list_tools():
    return TOOLS


@app.call_tool()
async def call_tool(name: str, arguments: dict):
    if name == "list_wordlists":
        entries = list_available_wordlists()
        lines = [f"  {e[0]:<15} {e[1]}" for e in entries]
        return [TextContent(type="text", text="可用字典:\n" + "\n".join(lines))]

    elif name == "run_scan":
        wordlist_path = resolve_wordlist(arguments.get("wordlist", "quick"))

        exts = None
        if arguments.get("extensions"):
            exts = [e.strip() for e in arguments["extensions"].split(",")]

        paths = load_dict(wordlist_path, exts)

        args = argparse.Namespace(
            url=arguments["url"],
            method="GET",
            concurrency=arguments.get("concurrency", 20),
            timeout=10,
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
            wildcard=False,
            no_wildcard=True,
            report=None,
            report_format="txt",
            data=None,
            delay=arguments.get("delay", 0),
            follow_redirect=False,
            recursion_status=None,
            show_diff=False,
            adaptive=False,
            pattern_learn=False,
            filter_sizes=None,
            filter_status=None,
            filter_time=None,
            filter_text=None,
            filter_regex=None,
            filter_headers=None,
            filter_redirect=None,
            filter_mode="or",
            match_status=None,
            match_sizes=None,
            match_time=None,
            match_text=None,
            match_regex=None,
            match_headers=None,
            matcher_mode="or",
        )

        headers = {"User-Agent": random_ua()}

        scanner = Scanner(args, None, None, headers, set(), paths, checkpoint_path=None)

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

        results = []
        for line in cap.lines:
            s = line.strip()
            if s and "[+]" in s:
                results.append(s)

        return [TextContent(type="text", text=
            f"目标: {arguments['url']}\n"
            f"字典: {arguments.get('wordlist', 'quick')} ({len(paths)} 条路径)\n"
            f"发现: {scanner.cnt}  已扫描: {scanner.scanned}\n"
            + "\n".join(results)
        )]

    raise ValueError(f"未知工具: {name}")


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
