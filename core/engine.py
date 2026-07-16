"""异步扫描引擎 + 过滤管道 + 通配符检测"""
import collections
import sys
import time
import aiohttp
import asyncio
from tqdm import tqdm
from core.scanner import scan_async
from core.config import color_status, EXTENSION_RECOGNITION_REGEX, DEFAULT_STATUS_CODE
from utils.crawl import extract_links
from utils.wildcard import WildcardProfile
from utils.output import ReportWriter
from utils.checkpoint import save_checkpoint, cleanup_checkpoint
from utils.diff import render_diff
from utils.rate_limit import AdaptiveRateLimiter
from utils.ext_probe import probe_extensions
from utils.filters import FilterPipeline
from utils.pattern_learn import PatternLearner


def _has_ext(path):
    """判断路径是否有文件扩展名"""
    return "." in path.rsplit("/", 1)[-1]


def build_filter_pipeline(args):
    """从 CLI 参数构建 FilterPipeline"""
    from utils.filters import FilterPipeline, parse_ranges, parse_time_filters
    f = {}
    # 基础（已有）
    exclude = set()
    if getattr(args, 'exclude_status', None):
        exclude.update(int(s.strip()) for s in args.exclude_status.split(","))
    include = set()
    if getattr(args, 'include_status', None):
        include = {int(s.strip()) for s in args.include_status.split(",")}
    f["exclude_status"] = exclude
    f["include_status"] = include
    f["max_size"] = getattr(args, 'max_size', None)
    f["min_size"] = getattr(args, 'min_size', None)

    # 新增
    try:
        f["filter_sizes"] = parse_ranges(getattr(args, 'filter_sizes', None))
    except ValueError:
        print(f"[-] 无效 --filter-sizes: {args.filter_sizes}")
        f["filter_sizes"] = ()
    try:
        f["filter_time"] = parse_time_filters(getattr(args, 'filter_time', None))
    except ValueError:
        print(f"[-] 无效 --filter-time: {args.filter_time}")
        f["filter_time"] = ()

    f["filter_status_codes"] = {int(s.strip()) for s in args.filter_status.split(",")} if getattr(args, 'filter_status', None) else set()
    f["filter_text"] = [t.strip() for t in args.filter_text.split(",")] if getattr(args, 'filter_text', None) else []
    f["filter_regex"] = getattr(args, 'filter_regex', None)
    f["filter_headers"] = [h.strip() for h in args.filter_headers.split(",")] if getattr(args, 'filter_headers', None) else []
    f["filter_redirect"] = getattr(args, 'filter_redirect', None)
    f["filter_mode"] = getattr(args, 'filter_mode', 'or')

    f["match_status_codes"] = {int(s.strip()) for s in args.match_status.split(",")} if getattr(args, 'match_status', None) else set()
    try:
        f["match_sizes"] = parse_ranges(getattr(args, 'match_sizes', None))
    except ValueError:
        print(f"[-] 无效 --match-sizes: {args.match_sizes}")
        f["match_sizes"] = ()
    try:
        f["match_time"] = parse_time_filters(getattr(args, 'match_time', None))
    except ValueError:
        print(f"[-] 无效 --match-time: {args.match_time}")
        f["match_time"] = ()
    f["match_text"] = [t.strip() for t in args.match_text.split(",")] if getattr(args, 'match_text', None) else []
    f["match_regex"] = getattr(args, 'match_regex', None)
    f["match_headers"] = [h.strip() for h in args.match_headers.split(",")] if getattr(args, 'match_headers', None) else []
    f["matcher_mode"] = getattr(args, 'matcher_mode', 'or')

    return FilterPipeline(args=f)


# 自动校准：同一指纹出现 N 次后自动封杀
_AUTO_CALIBRATION_THRESHOLD = 8
_AUTO_CALIBRATION_MIN_LENGTH = 32


class Scanner:
    def __init__(self, args, proxy, ssl, headers, include_status, wordlist_paths, resume_checkpoint=None, checkpoint_path=None):
        self.url = args.url
        self.args = args
        self.headers = headers
        self.proxy = proxy
        self.report_path = args.report
        self.report_format = args.report_format
        self.ssl = ssl
        self.quiet = args.quiet
        self.retries = args.retries
        self.include_status = include_status
        self.wordlist_paths = wordlist_paths
        self.method = args.method
        self.data = args.data
        self.follow_redirect = args.follow_redirect
        self.checkpoint_path = checkpoint_path
        if args.adaptive:
            self.ratelimiter = AdaptiveRateLimiter()

        # ── 检查点恢复 ──
        if resume_checkpoint:
            cp = resume_checkpoint
            self.urls = cp["urls"]
            self.seen = cp["seen"]
            self.scanned = cp["scanned"]
            self.cnt = cp["cnt"]
            self.wildcard_root = cp["wildcard_root"]
            self.wildcard_ext = cp["wildcard_ext"]
            self._scanned_paths = cp["scanned_paths"]
            self._current_url = cp.get("current_url")
            # 恢复自动校准状态
            self._fingerprint_counts = cp.get("fingerprint_counts", {})
            self._auto_calibrated = cp.get("auto_calibrated", set())
        else:
            self.urls = collections.deque([(self.url, 0)])
            self.seen = {self.url}
            self.scanned = 0
            self.cnt = 0
            self._scanned_paths = set()
            self._current_url = None

            # 通配符检测：root + extension 两个 context（异步探测延迟到 run()）
            self.wildcard_root = WildcardProfile()
            self.wildcard_ext = WildcardProfile()

        # 自动校准：指纹计数 + 已封杀指纹集合（独立于 wildcard 的第二道防线）
        self._fingerprint_counts = {}
        self._auto_calibrated = set()

        # 构建过滤规则
        self.recursion_codes = {200, 301, 302}  # 默认
        if self.args.recursion_status:
            self.recursion_codes = {int(s.strip()) for s in self.args.recursion_status.split(",")}

        # 高级过滤管道
        self.filter_pipe = build_filter_pipeline(self.args)

        # 模式学习器（反馈驱动变体生成）
        self.pattern_learner = PatternLearner()

    def add_url(self, url, depth):
        """ 去重后加入队列 """
        if url not in self.seen:
            self.urls.append((url, depth))
            self.seen.add(url)

    def should_skip(self, path, status, content, content_length, content_type, redirect_path, req_elapsed=0, resp_headers=None):
        """ 过滤管道，返回 True 表示跳过 """
        if resp_headers is None:
            resp_headers = {}

        # ── 基础过滤器 ──
        if self.filter_pipe.is_excluded_by_filter(
            status, content_length, content, req_elapsed, resp_headers, redirect_path
        ):
            return True

        # ── 高级匹配器 ──
        if not self.filter_pipe.passes_matchers(
            status, content_length, content, req_elapsed, resp_headers
        ):
            return True

        # 通配符检测：根据 path 选择对应的 profile
        profile = self.wildcard_ext if _has_ext(path) else self.wildcard_root
        if not self.args.no_wildcard and profile.is_wildcard(status, content_length, content, content_type, redirect_path):
            # --show-diff: 输出被过滤路径与 base 的差异
            if getattr(self.args, 'show_diff', False) and profile.base_content:
                self._show_diff_output(path, content, profile)
            return True

        # 自动校准：dirsearch 式第二道防线 — 同一指纹 ≥8 次自动封杀
        # （注意：WildcardProfile.record_fingerprint 阈值太低(3)，大字典下误杀严重，已移除）
        if self._is_auto_calibrated(path, status, content, content_length, content_type, redirect_path):
            return True

        return False

    def _is_auto_calibrated(self, path, status, content, content_length, content_type, redirect_path):
        """dirsearch 式的自动校准：同一指纹出现 ≥8 次自动封杀。

        触发条件：4xx/5xx 总是记录，或者路径回显在响应体中。
        指纹: (status, content_type, redirect, len//64, hash(body[:4096]))
        """
        if not self._should_record_auto_calib(status, path, content, redirect_path):
            return False

        fp = self._make_fingerprint(status, content_type, content_length, content, redirect_path)
        if fp in self._auto_calibrated:
            return True

        self._fingerprint_counts[fp] = self._fingerprint_counts.get(fp, 0) + 1
        if self._fingerprint_counts[fp] >= _AUTO_CALIBRATION_THRESHOLD:
            self._auto_calibrated.add(fp)
            return True

        return False

    @staticmethod
    def _make_fingerprint(status, content_type, content_length, content, redirect_path):
        """生成响应指纹：状态码 + 类型 + 重定向 + 粗粒度长度 + 内容前缀哈希"""
        return (
            status,
            content_type,
            redirect_path,
            content_length // 64,
            hash(content[:4096]) if isinstance(content, bytes) else hash(content[:4096].encode()),
        )

    @staticmethod
    def _should_record_auto_calib(status, path, content, redirect_path):
        """判断是否应该记录此响应用于自动校准"""
        # 有小内容不记录（太容易碰撞）
        if len(content) < _AUTO_CALIBRATION_MIN_LENGTH:
            return False
        # 4xx/5xx 总是记录
        if 400 <= status <= 599:
            return True
        # 路径回显在响应体中
        clean = path.strip("/")
        if clean:
            text = content.decode(errors="ignore") if isinstance(content, bytes) else content
            if clean in text:
                return True
        # 有重定向
        if redirect_path:
            return True
        return False

    def _show_diff_output(self, path, content, profile):
        """输出 wildcard 过滤路径与基准响应的 diff"""
        from tqdm import tqdm as _tqdm
        label_a = f"WILDCARD(base, {len(profile.base_content)}B)"
        label_b = f"/{path} (HTTP filtered, {len(content)}B)"
        # 只对比前 4KB 避免太长
        diff = render_diff(
            profile.base_content[:4096], content[:4096],
            label_a, label_b, context_lines=1
        )
        _tqdm.write(diff)

    def to_dict(self):
        """导出当前完整状态（用于 save_checkpoint）"""
        from utils.checkpoint import _serialize_wildcard
        return {
            "version": 1,
            "url": self.url,
            "wordlist_paths": self.wordlist_paths,
            "scanned_paths": self._scanned_paths,
            "urls": self.urls,
            "seen": self.seen,
            "scanned": self.scanned,
            "cnt": self.cnt,
            "wildcard_root": self.wildcard_root,
            "wildcard_ext": self.wildcard_ext,
            "current_url": getattr(self, '_current_url', None),
            "args": self.args,
        }

    async def run(self):
        start_time = time.time()
        report_writer = None
        if self.report_path:
            report_writer = ReportWriter(self.report_path, self.report_format)
        connector = aiohttp.TCPConnector(limit=self.args.concurrency)
        checkpoint_path = self.checkpoint_path
        last_save = time.time()

        async with aiohttp.ClientSession(connector=connector) as session:
            # 异步通配符探测（复用同一个 session）
            # 恢复时跳过探测，直接用已有 profile
            if not self.args.no_wildcard and not self._scanned_paths:
                await self.wildcard_root.detect_async(session, self.args, self.headers)
                await self.wildcard_ext.detect_async(session, self.args, self.headers, ext=".php")

            # 扩展名探测：确定优先扩展名，不丢不漏只排优先级
            self._priority_exts = set()
            if self.args.extension and not self._scanned_paths:
                exts = [e.strip() for e in self.args.extension.split(",")]
                if len(exts) > 1:
                    self._priority_exts = await probe_extensions(
                        session, self.url, exts, self.headers,
                        self.args.timeout, self.args.concurrency,
                    )
                    if self._priority_exts and not self.quiet:
                        tqdm.write(f"  [*] 探测命中扩展名: {', '.join(sorted(self._priority_exts))}")

            def _path_priority(path):
                """命中扩展名的路径排前面，未命中的排后面——不丢不漏"""
                if not self._priority_exts or "." not in path:
                    return 0
                # 取路径最后一个扩展名
                ext = path.rsplit(".", 1)[-1]
                return 0 if ext in self._priority_exts else 1

            try:
                while self.urls:
                    cur_url, depth = self.urls.popleft()
                    if depth >= self.args.depth:
                        continue

                    # 构建待扫描路径列表，跳过已扫描的
                    remaining = self.wordlist_paths
                    if self._scanned_paths:
                        remaining = [p for p in self.wordlist_paths if p not in self._scanned_paths]
                        if not remaining:
                            continue

                    # 命中扩展名的路径排前面，未命中排后面——不丢不漏
                    if self._priority_exts:
                        remaining = sorted(remaining, key=_path_priority)

                    results = [scan_async(session, cur_url, path, self.headers, self.method, self.proxy, self.ssl, self.follow_redirect, self.data, self.args.timeout, self.retries) for path in remaining]

                    pbar = tqdm(asyncio.as_completed(results), total=len(results), file=sys.stdout,
                                disable=not sys.stdout.isatty() or self.quiet)
                    for res in pbar:
                        self.scanned += 1
                        elapsed = time.time() - start_time
                        if elapsed != 0:
                            pbar.set_postfix(qps=f"{self.scanned / elapsed:.0f}")

                        path, status, redirect_path, content, content_type, req_elapsed, resp_headers = await res
                        self._scanned_paths.add(path)
                        content_length = len(content)

                        if self.args.adaptive:
                            self.ratelimiter.record(status)
                            if self.ratelimiter.should_step_up():
                                self.ratelimiter.step_up()
                            elif self.ratelimiter.should_step_down():
                                self.ratelimiter.step_down()
                            delay_time = self.args.delay + self.ratelimiter.penalty_delay
                        else:
                            delay_time = self.args.delay

                        if self.should_skip(path, status, content, content_length, content_type, redirect_path, req_elapsed, resp_headers):
                            await asyncio.sleep(delay_time)
                            continue

                        # 处理爬取模式
                        if self.args.crawl and status == 200 and "text/html" in content_type:
                            links = extract_links(content)
                            for link in links:
                                self.add_url(cur_url.rstrip("/") + "/" + link, depth + 1)

                        if status in DEFAULT_STATUS_CODE:
                            self.cnt += 1
                            if status != 301:
                                tqdm.write(
                                    f"  >>> [+] 发现: /{path} (HTTP {color_status(status, status)}), {content_length}B")
                            else:
                                tqdm.write(
                                    f"  >>> [+] 发现: /{path} -> {redirect_path} (HTTP {color_status(status, status)}), {content_length}B")

                            # 模式学习：只为有扩展名的命中路径生成变体（备份/隐藏文件）
                            if self.args.pattern_learn and depth + 1 < self.args.depth and _has_ext(path):
                                self.pattern_learner.on_hit(path, status, content_length, content_type)
                                extra_paths = self.pattern_learner.generate_variants(path)
                                # 后缀推广
                                last_seg = path.rsplit("/", 1)[-1]
                                if "." in last_seg:
                                    for suffix in [".bak", "~", ".old", ".orig"]:
                                        if path.endswith(suffix) and suffix not in self.pattern_learner.confirmed_suffixes:
                                            extra_paths.extend(self.pattern_learner.promote_suffix(suffix))
                                # 把变体路径作为独立扫描任务追加（绕过 wordlist 循环）
                                if extra_paths:
                                    results = [scan_async(session, cur_url, p, self.headers, self.method, self.proxy, self.ssl, self.follow_redirect, self.data, self.args.timeout, self.retries) for p in extra_paths]
                                    for res in asyncio.as_completed(results):
                                        path_v, status_v, redirect_path_v, content_v, content_type_v, req_elapsed_v, resp_headers_v = await res
                                        self.scanned += 1
                                        content_length_v = len(content_v)
                                        if not self.should_skip(path_v, status_v, content_v, content_length_v, content_type_v, redirect_path_v, req_elapsed_v, resp_headers_v):
                                            if status_v in DEFAULT_STATUS_CODE:
                                                self.cnt += 1
                                                tqdm.write(f"  >>> [+] 发现: /{path_v} (HTTP {color_status(status_v, status_v)}), {content_length_v}B (var)")
                                                self.pattern_learner.on_hit(path_v, status_v, content_length_v, content_type_v)

                            if self.args.recursive and status in self.recursion_codes:
                                if status == 200 and not EXTENSION_RECOGNITION_REGEX.search(path):
                                    if depth + 1 < self.args.depth:
                                        self.add_url(cur_url.rstrip("/") + "/" + path, depth + 1)
                                elif redirect_path.endswith("/"):
                                    if depth + 1 < self.args.depth:
                                        self.add_url(cur_url.rstrip("/") + redirect_path, depth + 1)
                            if self.report_path:
                                report_writer.add_result(path, status, content_length, redirect_path,  content_type)
                        await asyncio.sleep(delay_time)
                        # 定时自动保存 checkpoint
                        if checkpoint_path and time.time() - last_save > 30:
                            save_checkpoint(self, checkpoint_path)
                            last_save = time.time()



                # 扫描正常结束，清理 checkpoint
                if checkpoint_path:
                    cleanup_checkpoint(checkpoint_path)

            except KeyboardInterrupt:
                # Ctrl+C：保存进度后退出
                if checkpoint_path:
                    save_checkpoint(self, checkpoint_path)
                    tqdm.write(f"\n[*] 进度已保存到 {checkpoint_path}")
                    tqdm.write(f"[*] 已扫描 {self.scanned} 条，发现 {self.cnt} 个路径")
                    tqdm.write(f"[*] 下次恢复: python main.py -u {self.url} -w ... --resume {checkpoint_path}")
                else:
                    tqdm.write(f"\n[*] 扫描中断，已扫描 {self.scanned} 条，发现 {self.cnt} 个路径")
                return

        if self.report_path:
            report_writer.close()

        if not self.quiet:
            elapsed = time.time() - start_time
            qps = self.scanned / elapsed if elapsed > 0 else 0
            print(f"\n[*] 扫描完成！ 共发现 {self.cnt} 个路径，扫描 {self.scanned} 个，耗时 {elapsed:.2f}s，{qps:.0f} req/s")
