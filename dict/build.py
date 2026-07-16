"""字典 v3 — 深度清洗 + 智能分层
核心思想：高质量 > 高数量。多源共识 + 清洗规则 = 真正好用的字典。
"""
import re
from collections import OrderedDict
from pathlib import Path

RAW_DIR = Path(__file__).parent / "raw"
OUT_DIR = Path(__file__).parent

# 来源定义
SOURCES = {
    "seclists_raft_words.txt":    "seclists",
    "seclists_raft_dirs.txt":     "seclists",
    "weblist.txt":                "weblist",
    "hfuzz.txt":                  "hfuzz",
    "onelistforall_micro.txt":    "onelistforall",
    "oxgreyhound_quickhits.txt":  "oxgreyhound",
    "oxgreyhound_apidocs.txt":    "oxgreyhound",
    "assetnote_dirs.txt":         "assetnote",
}

# ─── 深度清洗 ──────────────────────────────────────────────────

# 控制字符
GARBAGE = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]')
# 太长
MAX_LEN = 256


def clean(line: str) -> str | None:
    """清洗一条路径，返回 None 表示丢弃"""
    line = line.strip()

    # 空、太长
    if not line or line in ("/", ""):
        return None
    if len(line) > MAX_LEN:
        return None

    # 控制字符
    if GARBAGE.search(line):
        return None

    # 去首 /
    line = line.lstrip("/")

    return line


def is_valuable(path: str) -> bool:
    """判断路径是否有价值（只过滤控制字符，保留一切可能合法的路径）"""
    # 控制字符
    if GARBAGE.search(path):
        return False
    # 太长
    if len(path) > MAX_LEN:
        return False
    return True


def load_all():
    """读取所有源，返回 {lower_path: {orig_paths, source_count, tags}}"""
    entries = OrderedDict()  # key = lowercase path

    for filename, src_label in SOURCES.items():
        fpath = RAW_DIR / filename
        if not fpath.exists():
            print(f"  [!] 跳过: {filename}")
            continue

        with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
            raw = keep = 0
            for line in f:
                raw += 1
                path = clean(line)
                if path is None:
                    continue
                if not is_valuable(path):
                    continue
                keep += 1

                key = path.lower()  # 大小写归一化
                if key not in entries:
                    entries[key] = {
                        "best_form": path,
                        "source_count": 0,
                        "source_labels": set(),
                    }
                e = entries[key]
                e["source_count"] += 1
                e["source_labels"].add(src_label)
                # 保留最自然的写法（优先有大小写混合的）
                if path.count("/") > e["best_form"].count("/"):
                    e["best_form"] = path

            print(f"  {filename}: {raw} → {keep} ({raw - keep} 垃圾)")

    return entries


def compute_quality(path: str, entry: dict) -> int:
    """综合质量分：多源共识 + 路径结构"""
    score = 0

    # 核心：来源数（每个源 10 分）
    score += entry["source_count"] * 10

    # 路径深度加分（有意义的子路径）
    depth = path.count("/")
    if depth == 0:
        pass  # 顶层路径
    elif depth == 1:
        score += 5   # 一级子目录
    elif depth >= 2:
        score += 8   # 深层路径，更精确

    # 包含常见高价值特征
    lower = path.lower()
    for kw in ["admin", "api", "config", "backup", "login", "debug",
               "upload", "download", "shell", "install", "setup"]:
        if kw in lower:
            score += 3

    return score


def main():
    print("[*] dict build v3 — 深度清洗 + 智能分层")
    entries = load_all()

    # ── 按质量分排序 ──
    sorted_all = sorted(entries.items(),
                        key=lambda x: compute_quality(x[0], x[1]),
                        reverse=True)

    total = len(sorted_all)
    print(f"\n[*] 去重+清洗后: {total} 条")

    # ── 分层 ──
    tiers = [
        ("quick.txt",    lambda sc: sc >= 4, "≥4源共识"),
        ("standard.txt", lambda sc: sc >= 3, "≥3源共识"),
        ("full.txt",     lambda sc: sc >= 2, "≥2源共识"),
    ]

    for fname, cond, desc in tiers:
        filtered = [(p, e) for p, e in sorted_all if cond(e["source_count"])]
        fpath = OUT_DIR / fname
        with open(fpath, "w", encoding="utf-8") as f:
            for path, entry in filtered:
                f.write(f"{entry['best_form']}\n")
        size_kb = fpath.stat().st_size / 1024
        print(f"  {fname:15s} {len(filtered):>6} 条  {size_kb:>6.0f} KB  {desc}")

    # ── 按模式分类（每个层级） ──
    CATEGORIES = {
        "api":       r"(^|[/._-])(api|graphql|swagger|openapi|rest|v\d+|oauth|token|endpoint|soap|webhook|health)",
        "backups":   r"\.(bak|old|backup|orig|swp|swo|tmp|temp|save)|\.(sql|zip|tar|gz|tgz|7z|rar)|/(backup|old|archive|dump)",
        "config":    r"\.(conf|config|ini|cfg|env|json|yml|yaml|xml|toml|properties)|^(\.env|\.git|\.svn|\.hg|\.DS_Store|\.ht|web\.config|composer\.|package\.|Dockerfile|Makefile)",
        "logs":      r"\.log|/(log|error|debug|trace|audit)",
        "cms":       r"wp-|wordpress|joomla|drupal|magento|typo3|cms|concrete|prestashop|shopify|woocommerce",
        "admin":     r"(^|/)(admin|administrator|panel|dashboard|manage|cp|cpanel|backend)",
    }

    for tier_name, _, _ in tiers:
        tier_path = OUT_DIR / tier_name
        if not tier_path.exists():
            continue
        with open(tier_path, encoding="utf-8") as f:
            tier_paths = [l.strip() for l in f if l.strip()]

        for cat_name, cat_regex in CATEGORIES.items():
            regex = re.compile(cat_regex, re.I)
            matched = [p for p in tier_paths if regex.search("/" + p)]
            if matched:
                cat_path = OUT_DIR / f"{tier_name.replace('.txt','')}_{cat_name}.txt"
                with open(cat_path, "w", encoding="utf-8") as f:
                    for p in matched:
                        f.write(f"{p}\n")
                if tier_name == "quick.txt":
                    print(f"  {cat_path.name:25s} {len(matched):>6} 条")

    print(f"\n{'='*55}")
    for tier_name, cond, desc in tiers:
        tpath = OUT_DIR / tier_name
        if tpath.exists():
            count = sum(1 for _ in open(tpath, encoding="utf-8", errors="ignore"))
            size_kb = tpath.stat().st_size / 1024
            print(f"  {tier_name:15s} {count:>6} 条  {size_kb:>7.0f} KB   {desc}")


if __name__ == "__main__":
    main()
