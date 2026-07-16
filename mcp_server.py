"""scent MCP Server — expose web fuzzing to AI agents"""
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
        description="Scan a target URL for hidden directories and files",
        inputSchema={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Target URL, e.g. http://example.com"},
                "wordlist": {"type": "string", "description": "Wordlist name (quick/standard/full) or path to file"},
                "concurrency": {"type": "integer", "default": 20},
                "extensions": {"type": "string", "description": "Comma-separated extensions, e.g. php,html"},
                "recursive": {"type": "boolean", "default": False},
                "depth": {"type": "integer", "default": 3},
                "delay": {"type": "number", "default": 0, "description": "Delay between requests in seconds"},
            },
            "required": ["url"],
        },
    ),
    Tool(
        name="list_wordlists",
        description="List available built-in wordlists",
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
            entries.append((name, f"{lines:,} paths"))
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
        return [TextContent(type="text", text="Available wordlists:\n" + "\n".join(lines))]

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
            if s and ("[+]" in s):
                results.append(s)

        return [TextContent(type="text", text=
            f"target: {arguments['url']}\n"
            f"wordlist: {arguments.get('wordlist', 'quick')} ({len(paths)} paths)\n"
            f"found: {scanner.cnt}  scanned: {scanner.scanned}\n"
            + "\n".join(results)
        )]

    raise ValueError(f"Unknown tool: {name}")


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
