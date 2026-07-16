"""高级过滤：数值范围、时间、文本、正则、响应头"""
import re


# ─── 数值范围解析 ──────────────────────────────────────────────

def parse_ranges(value):
    """解析 "100-200,500-600" → ((100,200), (500,600))"""
    if not value:
        return ()
    ranges = []
    for token in value.split(","):
        token = token.strip()
        if not token:
            continue
        if "-" in token:
            a, b = token.split("-", 1)
            try:
                lo, hi = int(a), int(b)
            except ValueError:
                raise ValueError(f"无效范围: {token}")
            if lo > hi:
                raise ValueError(f"无效范围: {token}")
            ranges.append((lo, hi))
        else:
            try:
                n = int(token)
            except ValueError:
                raise ValueError(f"无效数值: {token}")
            ranges.append((n, n))
    return tuple(ranges)


def in_ranges(value, ranges):
    """value 是否落在一组范围中的任一范围内"""
    return any(lo <= value <= hi for lo, hi in ranges)


# ─── 时间过滤 ──────────────────────────────────────────────────

def parse_time_filters(value):
    """解析 ">500,<100" → ((">", 500), ("<", 100))  单位 ms"""
    if not value:
        return ()
    filters = []
    for token in value.split(","):
        token = token.strip()
        if not token:
            continue
        op = "="
        if token[0] in (">", "<"):
            op, token = token[0], token[1:]
        try:
            filters.append((op, float(token)))
        except ValueError:
            raise ValueError(f"无效时间过滤: {token}")
    return tuple(filters)


def matches_time(elapsed_seconds, filters):
    """elapsed_seconds 是否满足时间过滤条件"""
    ms = elapsed_seconds * 1000
    for op, val in filters:
        if op == ">" and ms > val:
            return True
        if op == "<" and ms < val:
            return True
        if op == "=" and ms == val:
            return True
    return False


# ─── 内容过滤 ──────────────────────────────────────────────────

def matches_text(content, patterns, mode="any"):
    """响应体是否包含任一/全部指定文本"""
    if not patterns:
        return mode != "any"  # 无 patterns 时 any→False, all→True
    text = content.decode(errors="ignore") if isinstance(content, bytes) else content
    text_lower = text.lower()
    if mode == "all":
        return all(p.lower() in text_lower for p in patterns)
    return any(p.lower() in text_lower for p in patterns)


def matches_regex(content, pattern, flags=re.IGNORECASE):
    """响应体是否匹配正则"""
    if not pattern:
        return False
    text = content.decode(errors="ignore") if isinstance(content, bytes) else content
    return bool(re.search(pattern, text, flags))


def matches_headers(headers_dict, patterns):
    """响应头是否包含指定文本"""
    if not patterns:
        return False
    header_text = "\n".join(f"{k}: {v}" for k, v in (headers_dict or {}).items()).lower()
    return any(p.lower() in header_text for p in patterns)


# ─── matcher / filter 模式 ─────────────────────────────────────

def combine_checks(checks, mode, default):
    """按 and/or 模式合并多个检查结果。无检查时返回 default"""
    if not checks:
        return default
    return all(checks) if mode == "and" else any(checks)


# ─── FilterPipeline（封装整个过滤流程）─────────────────────────

class FilterPipeline:
    """封装 matches（必须满足才报告）和 filters（满足任一即排除）两套规则"""

    def __init__(self, args=None):
        self.args = args or {}

    def is_excluded_by_filter(self, status, length, content, elapsed, headers, redirect):
        """返回 True 表示应排除"""
        f = self.args

        # ── 状态码 ──
        if f.get("exclude_status") and status in f["exclude_status"]:
            return True
        if f.get("include_status") and status not in f["include_status"]:
            return True

        # ── 响应大小 ──
        if f.get("max_size") is not None and length > f["max_size"]:
            return True
        if f.get("min_size") is not None and length < f["min_size"]:
            return True

        # ── filter 规则 ──
        checks = []

        if f.get("filter_sizes"):
            checks.append(in_ranges(length, f["filter_sizes"]))
        if f.get("filter_status_codes"):
            checks.append(status in f["filter_status_codes"])
        if f.get("filter_time"):
            checks.append(matches_time(elapsed, f["filter_time"]))
        if f.get("filter_text"):  # 改为 list
            checks.append(matches_text(content, f["filter_text"]))
        if f.get("filter_regex"):
            checks.append(matches_regex(content, f["filter_regex"]))
        if f.get("filter_headers"):
            checks.append(matches_headers(headers, f["filter_headers"]))
        if f.get("filter_redirect"):
            checks.append(
                redirect and (f["filter_redirect"] in redirect
                              or bool(re.search(f["filter_redirect"], redirect, re.I)))
            )

        return combine_checks(checks, f.get("filter_mode", "or"), default=False)

    def passes_matchers(self, status, length, content, elapsed, headers):
        """返回 True 表示通过匹配器（可以报告）"""
        f = self.args
        checks = []

        if f.get("match_status_codes"):
            checks.append(status in f["match_status_codes"])
        if f.get("match_sizes"):
            checks.append(in_ranges(length, f["match_sizes"]))
        if f.get("match_time"):
            checks.append(matches_time(elapsed, f["match_time"]))
        if f.get("match_text"):
            checks.append(matches_text(content, f["match_text"]))
        if f.get("match_regex"):
            checks.append(matches_regex(content, f["match_regex"]))
        if f.get("match_headers"):
            checks.append(matches_headers(headers, f["match_headers"]))

        return combine_checks(checks, f.get("matcher_mode", "or"), default=True)
