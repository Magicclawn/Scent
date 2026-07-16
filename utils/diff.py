"""响应体 diff 引擎 — unified_diff + colorama 彩色渲染"""
import difflib

from colorama import Fore, Style


def normalize_for_diff(content):
    """轻量归一化：bytes→str，不做深度 HTML 清理（diff 要保留原样）"""
    if isinstance(content, bytes):
        content = content.decode("utf-8", errors="ignore")
    return content


def render_diff(content_a, content_b, label_a="A", label_b="B", context_lines=3):
    """对两个内容做 unified_diff，返回彩色 ANSI 字符串

    参数:
      content_a / content_b: bytes 或 str
      label_a / label_b: 对比标签（显示在 diff header 中）
      context_lines: unified diff 的上下文行数

    返回:
      彩色 diff 字符串，适合直接 tqdm.write()
    """
    text_a = normalize_for_diff(content_a)
    text_b = normalize_for_diff(content_b)

    lines_a = text_a.splitlines(keepends=True)
    lines_b = text_b.splitlines(keepends=True)

    diff = list(difflib.unified_diff(
        lines_a, lines_b,
        fromfile=label_a, tofile=label_b,
        n=context_lines,
    ))

    if not diff:
        return f"{Fore.WHITE}[*] 两个响应体完全一致 (相同大小){Style.RESET_ALL}"

    # 渲染
    out = []
    for line in diff:
        line = line.rstrip("\n")
        if line.startswith("---") or line.startswith("+++"):
            out.append(f"{Fore.YELLOW}{Style.BRIGHT}{line}{Style.RESET_ALL}")
        elif line.startswith("@@"):
            out.append(f"{Fore.CYAN}{Style.BRIGHT}{line}{Style.RESET_ALL}")
        elif line.startswith("+"):
            out.append(f"{Fore.GREEN}{line}{Style.RESET_ALL}")
        elif line.startswith("-"):
            out.append(f"{Fore.RED}{line}{Style.RESET_ALL}")
        else:
            out.append(line)

    return "\n".join(out)
