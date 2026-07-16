"""通配符检测：多探测 + 静态token + 重定向匹配"""

import random
import re
import difflib
import aiohttp

from core.config import DYNAMIC_PATTERNS, STEALTH_WORDS


class _ProbeResult:
    """aiohttp 响应包装：async with 退出后 status/content/headers 仍可用"""
    __slots__ = ('status', 'content', 'headers')
    def __init__(self, status, content, headers):
        self.status = status
        self.content = content
        self.headers = headers


class WildcardProfile:
    def __init__(self):
        self.status_codes = set()
        self.content_lengths = set()
        self.content_hashes = set()
        self.is_static = False
        self.redirect_regex = None
        self.static_tokens = set()
        self.fingerprint_counts = {}
        self.base_content = b""
        self._static_tokens = [] # 保存原始顺序，用于有序匹配

    async def _probe_async(self, session, url, headers, timeout):
        """异步探测请求，复用外部 ClientSession，返回 _ProbeResult 或 None"""
        try:
            async with session.get(url, headers=headers, timeout=timeout, allow_redirects=False) as resp:
                body = await resp.read()
                return _ProbeResult(resp.status, body, resp.headers)
        except aiohttp.ClientError:
            return None

    def _stealth_word(self):
        parts = random.sample(STEALTH_WORDS, random.randint(2, 3))
        return "-".join(parts)

    def _is_probable_wildcard(self, content_length, content):
        """ 保守兜底：相似度 > 0.75 + 长度差 < 0.35 """
        if not self.base_content or content_length == 0:
            return False

        base_len = len(self.base_content)
        if content_length > 262144:
            return False

        text = self.normalize_content(content)
        base_text = self.normalize_content(self.base_content)

        similarity = difflib.SequenceMatcher(None, text, base_text).ratio()
        length_delta = abs(content_length - base_len) / max(base_len, 1)

        return similarity > 0.90 and length_delta < 0.25

    def _generate_redirect_regex(self, loc1, loc2):
        """从两个重定向 URL 生成模糊匹配正则"""
        min_len = min(len(loc1), len(loc2))
        i = 0
        while i < min_len and loc1[i] == loc2[i]:
            i += 1
        prefix = re.escape(loc1[:i])

        j = min_len - 1
        while j >= 0 and loc1[j] == loc2[j]:
            j -= 1
        suffix = re.escape(loc2[j + 1:])

        return re.compile(f"^{prefix}.*{suffix}$")

    def _extract_static_tokens(self, base_content, other_contents):
        """ 用 Differ 提取所有探测响应中都存在的 token(保留顺序) """
        base_tokens = self._tokenize(base_content)
        static_tokens = set(base_tokens)

        differ = difflib.Differ()
        for content in other_contents:
            other_tokens = self._tokenize(content)
            diff = list(differ.compare(base_tokens, other_tokens))

            common = {token[2:] for token in diff if token.startswith("  ")}
            static_tokens &= common

        ordered = [t for t in base_tokens if t in static_tokens and len(t) > 2]
        self._static_tokens = ordered
        self.static_tokens = set(ordered)

    def _tokenize(self, content):
        text = self.normalize_content(content)
        # 剥离 HTML 标签，只保留文字内容
        text = re.sub(r'<[^>]*>', ' ', text)
        return text.split()

    def normalize_content(self, content):
        if isinstance(content, bytes):
            content = content.decode("utf-8", errors="ignore")
        for pattern, replacement in DYNAMIC_PATTERNS:
            content = pattern.sub(replacement, content)
        return content

    async def detect_async(self, session, args, headers, ext=""):
        """异步版通配符检测，复用外部 ClientSession"""
        redirects = []
        base = args.url.rstrip("/")
        probe_url = lambda: f"{base}/{self._stealth_word()}{ext}"

        resp1 = await self._probe_async(session, probe_url(), headers, args.timeout)
        if not resp1:
            return
        self.base_content = resp1.content

        self.status_codes.add(resp1.status)
        self.content_lengths.add(len(resp1.content))
        self.content_hashes.add(hash(resp1.content))

        loc = resp1.headers.get("Location", "")
        if loc:
            redirects.append(loc)

        all_resps = set()
        all_resps.add(resp1)

        for _ in range(2):
            resp = await self._probe_async(session, probe_url(), headers, args.timeout)
            all_resps.add(resp)
            if not resp:
                continue

            loc = resp.headers.get("Location", "")
            if loc:
                redirects.append(loc)
                if len(redirects) >= 2:
                    self.redirect_regex = self._generate_redirect_regex(redirects[0], redirects[1])

            self.status_codes.add(resp.status)
            self.content_lengths.add(len(resp.content))
            self.content_hashes.add(hash(resp.content))

            if resp1.content == resp.content:
                self.is_static = True

        self._extract_static_tokens(resp1.content, [r.content for r in all_resps])


    def _match_length(self, content_length):
        if not self.content_lengths:
            return False
        for base_len in self.content_lengths:
            diff = abs(content_length - base_len)
            tolerance = max(base_len * 0.03, 5)
            if diff <= tolerance:
                return True
        return False

    def _match_tokens(self, content):
        if not self.static_tokens:
            return False
        tokens = self._tokenize(content)
        if len(tokens) < len(self._static_tokens) * 2:
            return False
        pos = 0
        matched = 0

        for token in self._static_tokens:
            try:
                idx = tokens.index(token, pos)
                matched += 1
                pos = idx + 1
            except ValueError:
                pass

        return matched / len(self._static_tokens) > 0.8

    def is_wildcard(self, status, content_length, content, content_type, redirect_path):
        if self.redirect_regex:
            if status not in (301, 302):
                return False
            elif self.redirect_regex.match(redirect_path):
                return True

        if "text/html" not in content_type:
            return False

        if status not in self.status_codes:
            return False

        if self.is_static:
            return hash(content) in self.content_hashes

        # 动态模板：长度 + token 都匹配才是 wildcard（缺一不可）
        if self._match_length(content_length) and self._match_tokens(content):
            return True

        return self._is_probable_wildcard(content_length, content)
