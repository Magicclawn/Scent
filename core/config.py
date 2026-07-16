"""状态码颜色 + UA池 + Banner"""

import sys
import random
import re
from colorama import init, Fore, Style

try:
    import pyfiglet
    _SCENT_LOGO = pyfiglet.figlet_format("SCENT", font="graffiti")
except ImportError:
    _SCENT_LOGO = """  _____  _____ ______ _   _ _______
 / ____|/ ____|  ____| \\ | |__   __|
| (___ | |    | |__  |  \\| |  | |
 \\___ \\| |    |  __| | . ` |  | |
 ____) | |____| |____| |\\  |  | |
|_____/ \\_____|______|_| \\_|  |_|"""

_logo_lines = _SCENT_LOGO.rstrip("\n").split("\n")
_logo_width = max(len(l) for l in _logo_lines)  # 51

# 渐变色: 从上到下蓝→青→绿
_colors = [Fore.BLUE, Fore.LIGHTBLUE_EX, Fore.CYAN, Fore.LIGHTCYAN_EX, Fore.LIGHTGREEN_EX, Fore.GREEN]
_colored_lines = []
for i, line in enumerate(_logo_lines):
    ci = min(i * len(_colors) // max(len(_logo_lines), 1), len(_colors) - 1)
    _colored_lines.append(f"{_colors[ci]}{line.center(_logo_width)}")

# 手工居中（ANSI 码不算宽度）
def _center_visible(text, width):
    """按可见字符居中，忽略 ANSI 转义码"""
    import re
    visible = re.sub(r'\x1b\[[0-9;]*m', '', text)
    pad = (width - len(visible)) // 2
    return f"{' ' * max(pad, 0)}{text}"

_tagline = f"{Fore.YELLOW}⚡ feedback-driven web fuzzer v2.9 ⚡"
_subtitle = f"{Fore.WHITE}follow the scent. find the path."
_divider = f"{Fore.MAGENTA}{'━' * _logo_width}{Style.RESET_ALL}"

BANNER = f"""{_divider}
{chr(10).join(_colored_lines)}{Style.RESET_ALL}
{_center_visible(_tagline, _logo_width)}
{_center_visible(_subtitle, _logo_width)}
{_divider}
"""

EXTENSION_RECOGNITION_REGEX = re.compile(r"\w+([.][a-zA-Z0-9]{2,5}){1,3}~?$")
DEFAULT_STATUS_CODE = (200, 301, 302, 401, 403, 500)
COMMON_HTML_BOILERPLATE = {
    "<html>", "</html>", "<head>", "</head>",
    "<body>", "</body>", "<!doctype html>",
    "<!DOCTYPE html>", "<html lang=\"en\">",
    "<meta charset=\"utf-8\">", "</meta>",
    "<h1>", "</h1>", "<p>", "</p>", "<title>",
    "</title>"
}
DYNAMIC_PATTERNS = [
    (re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I), "<UUID>"),
    (re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}"), "<TIMESTAMP>"),
    (re.compile(r"token=\w+"), "token=<TOKEN>"),
    (re.compile(r"session=\w+"), "session=<SESSION>"),
    (re.compile(r'nonce="[^"]+"'), 'nonce="<VALUE>"'),
    (re.compile(r"csrf_token=\w+"), "<CSRF>"),
    (re.compile(r"request[-_]?id=[\w-]+"), "<REQ_ID>"),
    (re.compile(r"trace[-_]?id=[\w-]+"), "<TRACE_ID>"),
    (re.compile(r"[A-Za-z0-9+/]{24,}={0,2}"), "<BASE64>"),
    (re.compile(r"[0-9a-f]{16,}"), "<HEX>"),
    (re.compile(r"\d{1,2}:\d{2}:\d{2}"), "<TIME>"),
    (re.compile(r"(?<!\w)\d{6,}(?!\w)"), "<INT>")
]
STEALTH_WORDS = [
    "cyberflux", "luminary", "chronos", "vertex", "nexus", "quantum",
    "aurora", "zenith", "cascade", "phoenix", "stellar", "obsidian",
    "crystal", "nebula", "vortex", "horizon", "prism", "eclipse",
    "phantom", "ember"
]

# Windows终端编码修复 + colorama初始化
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    init()

# ─── 默认 User-Agent 列表 ─────────────────────────────────────
DEFAULT_UAS = [
    # Chrome (Windows)
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    # Chrome (macOS)
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    # Chrome (Linux)
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    # Firefox (Windows)
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    # Firefox (macOS)
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.5; rv:126.0) Gecko/20100101 Firefox/126.0",
    # Firefox (Linux)
    "Mozilla/5.0 (X11; Linux x86_64; rv:126.0) Gecko/20100101 Firefox/126.0",
    # Safari (macOS)
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
    # Edge (Windows)
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36 Edg/125.0.0.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0",
    # Chrome (Android)
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Mobile Safari/537.36",
    # Safari (iOS)
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (iPad; CPU OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
    # Googlebot (搜索引擎爬虫，混入可以降低被检测概率)
    "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
    "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; Googlebot/2.1; +http://www.google.com/bot.html) Chrome/120.0.0.0 Safari/537.36",
]


def random_ua():
    """随机返回一个 User-Agent"""
    return random.choice(DEFAULT_UAS)

# 状态码 → 颜色映射
STATUS_COLORS = {
    200: Fore.GREEN,      # 找到页面 - 绿色
    301: Fore.YELLOW,     # 永久重定向 - 黄色
    302: Fore.YELLOW,     # 临时重定向 - 黄色
    401: Fore.BLUE,
    403: Fore.MAGENTA,    # 禁止访问 - 品红
    404: Style.DIM,       # 未找到 - 灰色
    500: Fore.RED,        # 服务器错误 - 红色
}

def color_status(status, text):
    """给状态文本加上对应颜色的 ANSI 转义码"""
    if status is None:
        return f"{Fore.RED}{text}{Style.RESET_ALL}"  # 请求失败
    color = STATUS_COLORS.get(status, Fore.WHITE)
    return f"{color}{text}{Style.RESET_ALL}"

