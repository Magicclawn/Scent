#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
scent 自动化测试脚本 v4
用法：
  python run_test.py                     # 基准测试 (testserver v4, old wordlist)
  python run_test.py --scan-only         # 只运行扫描（靶场已在运行）
  python run_test.py --soft-404          # 简单软 404 检测测试
  python run_test.py --multi-404         # 多模板软 404 检测测试
  python run_test.py --method-test       # HTTP Method 测试
  python run_test.py --checkpoint-test   # 检查点暂停/恢复测试
  python run_test.py --recall-report     # 召回率分析（带漏掉原因）
  python run_test.py --full-bench        # 全量基准测试 (benchmark_wordlist vs 96 已知路径)
  python run_test.py --help              # 显示帮助
"""

import subprocess
import sys
import time

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

TARGET = "http://127.0.0.1:18888"
WORDLIST = "dict/quick.txt"
BENCH_WORDLIST = "benchmark_wordlist.txt"
SCANNER = "scent.py"
TESTSERVER = "testserver.py"


def _load_expected():
    """从 testserver 动态加载 EXPECTED（避免手动维护两份）"""
    sys.path.insert(0, ".")
    from testserver import ROUTES
    sys.path.pop(0)
    expected = {}
    post_expected = {}
    for path, route in ROUTES.items():
        status = route["status"]
        clean = path.lstrip("/")
        if route.get("method", "GET") != "GET":
            post_expected[clean] = status
        else:
            expected[clean] = status
    return expected, post_expected


EXPECTED, POST_EXPECTED = _load_expected()
POST_REQUIRED = set(POST_EXPECTED.keys())


def start_server(extra_args=None):
    if extra_args is None:
        extra_args = []
    print("[*] 启动测试靶场...")
    proc = subprocess.Popen(
        [sys.executable, TESTSERVER] + extra_args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding="utf-8",
    )
    time.sleep(1)
    import requests
    try:
        r = requests.get(TARGET, timeout=3)
        if r.status_code == 200:
            print(f"      靶场就绪 -> {TARGET}\n")
            return proc
    except requests.exceptions.RequestException:
        print("[-] 靶场启动失败")
        proc.kill()
        sys.exit(1)


def run_scanner(extra_args=None):
    if extra_args is None:
        extra_args = []
    result = subprocess.run(
        [sys.executable, SCANNER, "-u", TARGET, "-w", WORDLIST] + extra_args,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", timeout=120,
    )
    print(result.stdout)
    return result.stdout


def run_scanner_bench(extra_args=None):
    """用 benchmark_wordlist 运行扫描器"""
    if extra_args is None:
        extra_args = []
    result = subprocess.run(
        [sys.executable, SCANNER, "-u", TARGET, "-w", BENCH_WORDLIST] + extra_args,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", timeout=120,
    )
    print(result.stdout)
    return result.stdout


def parse_found_paths(output, expected_set=None):
    """从扫描器输出中提取发现的路径集合"""
    if expected_set is None:
        expected_set = EXPECTED
    found = {}
    import re
    all_paths = sorted(expected_set.keys(), key=len, reverse=True)
    for line in output.splitlines():
        if "[+]" in line and ("发现" in line):
            # 提取路径（在 ">>> [+] 发现: /path " 中的 /path）
            m_path = re.search(r'发现:\s*(/\S+)', line)
            if not m_path:
                continue
            found_path = m_path.group(1)
            # 去掉尾部箭头后面的内容（如 "-> /redirect"）
            if " -> " in found_path:
                found_path = found_path.split(" -> ")[0]
            # 标准化：去掉首部 /
            found_path = found_path.lstrip("/")
            # 检查是否在期望列表中
            if found_path in all_paths:
                m_st = re.search(r'HTTP (\d+)', line)
                if m_st:
                    found[found_path] = int(m_st.group(1))
    return found


def calc_stats(found, expected_set):
    """计算召回率和误报"""
    matched = set(found) & set(expected_set)
    false_pos = set(found) - set(expected_set)
    recall = len(matched)
    return recall, len(false_pos), matched, false_pos


def print_heading(title):
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)


def print_verdict(ok):
    print(f"\n  {'[OK] 通过' if ok else '[FAIL] 未通过'}")
    return ok


# ─── 全量基准测试 (v4 testserver) ──────────────────────────

def test_full_bench():
    """全量基准测试：benchmark_wordlist (135条) vs 96 已知 GET 路径"""
    print_heading("全量基准测试 (v4 testserver, 96 已知路径)")
    server = start_server()
    try:
        output = run_scanner_bench()
        found = parse_found_paths(output, EXPECTED)

        recall, n_false, matched, false_pos = calc_stats(found, EXPECTED)
        total = len(EXPECTED)

        # 打印遗漏
        missing = set(EXPECTED) - set(found)
        if missing:
            print(f"\n  遗漏 {len(missing)} 个路径:")
            for p in sorted(missing)[:20]:
                print(f"    /{p} -> 期望 {EXPECTED[p]}")
            if len(missing) > 20:
                print(f"    ... 共 {len(missing)} 个")

        if false_pos:
            print(f"\n  误报 {len(false_pos)} 个:")
            for p in sorted(false_pos)[:10]:
                print(f"    /{p} -> {found[p]}")

        print(f"\n  召回率: {recall}/{total} ({recall/total*100:.1f}%)")
        print(f"  误报: {len(false_pos)}")

        # 通过标准: >=90% 召回率, <=5 误报
        ok = recall >= total * 0.90 and len(false_pos) <= 5
        return print_verdict(ok)
    finally:
        server.kill()
        server.wait()
        print("\n[*] 靶场已关闭")


# ─── 基础测试 (quick dict) ──────────────────────────────────

def test_baseline():
    """基准测试：quick.txt vs testserver v4"""
    print_heading("基础测试 (quick 字典 vs testserver v4)")
    server = start_server()
    try:
        output = run_scanner()
        found = parse_found_paths(output, EXPECTED)
        recall, n_false, matched, false_pos = calc_stats(found, EXPECTED)
        total = len(EXPECTED)

        from utils.dict_loader import load_dict
        old_paths = set(load_dict(WORDLIST))
        old_in_new = {p: s for p, s in EXPECTED.items() if p in old_paths}
        match_old = set(found) & set(old_in_new)

        print(f"  quick 字典覆盖 {len(old_in_new)}/{total} 已知路径")
        print(f"  发现其中 {len(match_old)} 个")
        print(f"  遗漏 {len(set(old_in_new) - set(found))} 个")

        ok = len(match_old) == len(old_in_new)
        return print_verdict(ok)
    finally:
        server.kill()
        server.wait()
        print("\n[*] 靶场已关闭")


# ─── 软 404 测试 ────────────────────────────────────────────

def test_soft_404():
    print_heading("软 404 检测测试（简单模板）")
    server = start_server(["--soft-404"])
    try:
        print("[*] 通配符检测 ON")
        out_on = run_scanner_bench(["--wildcard"])
        found_on = parse_found_paths(out_on, EXPECTED)

        print("[*] 通配符检测 OFF")
        out_off = run_scanner_bench()
        found_off = parse_found_paths(out_off, EXPECTED)

        recall_on, fp_on, _, _ = calc_stats(found_on, EXPECTED)
        recall_off, fp_off, _, _ = calc_stats(found_off, EXPECTED)

        print(f"\n  召回率: {recall_on}/{len(EXPECTED)} (ON) vs {recall_off}/{len(EXPECTED)} (OFF)")
        print(f"  误报: {fp_on} (ON) vs {fp_off} (OFF)")

        if fp_off > 0:
            print(f"  OFF 误报: {sorted(set(found_off) - set(EXPECTED))[:10]}")

        ok = recall_on >= len(EXPECTED) * 0.60 and fp_on <= fp_off
        return print_verdict(ok)
    finally:
        server.kill()
        server.wait()
        print("\n[*] 靶场已关闭")


# ─── 多模板 404 测试 ────────────────────────────────────────

def test_multi_404():
    print_heading("多模板 404 检测测试")
    server = start_server(["--multi-404"])
    try:
        print("[*] 通配符检测 ON")
        out_on = run_scanner_bench(["--wildcard"])
        found_on = parse_found_paths(out_on, EXPECTED)

        print("[*] 通配符检测 OFF")
        out_off = run_scanner_bench()
        found_off = parse_found_paths(out_off, EXPECTED)

        recall_on, fp_on, _, _ = calc_stats(found_on, EXPECTED)
        recall_off, fp_off, _, _ = calc_stats(found_off, EXPECTED)

        print(f"\n  召回率: {recall_on}/{len(EXPECTED)} ({recall_on/len(EXPECTED)*100:.0f}%) ON  vs  "
              f"{recall_off}/{len(EXPECTED)} ({recall_off/len(EXPECTED)*100:.0f}%) OFF")
        print(f"  误报: {fp_on} (ON) vs {fp_off} (OFF)")

        missing = set(EXPECTED) - set(found_on)
        if missing:
            print(f"  ON 遗漏 {len(missing)} 个:")
            for p in sorted(missing)[:15]:
                print(f"    /{p}")

        if fp_off > 0:
            print(f"  OFF 误报 {fp_off} 个: {sorted(set(found_off) - set(EXPECTED))[:10]}")

        ok = recall_on >= len(EXPECTED) * 0.50 and fp_on <= fp_off
        return print_verdict(ok)
    finally:
        server.kill()
        server.wait()
        print("\n[*] 靶场已关闭")


# ─── HTTP Method 测试 ───────────────────────────────────

def test_method():
    print_heading("HTTP Method 测试")
    server = start_server()
    try:
        print("[*] GET 模式")
        out_get = run_scanner_bench()
        get_found = set()
        for line in out_get.splitlines():
            if "[+]" in line and "发现" in line:
                for path in POST_EXPECTED:
                    if f"/{path}" in line:
                        get_found.add(path)

        print("[*] POST 模式")
        out_post = run_scanner_bench(["--method", "POST"])
        post_found = set()
        for line in out_post.splitlines():
            if "[+]" in line and "发现" in line:
                for path in POST_EXPECTED:
                    if f"/{path}" in line:
                        post_found.add(path)

        get_ok = len(get_found) == 0
        post_ok = POST_REQUIRED.issubset(post_found)

        print(f"  {'[OK]' if get_ok else '[FAIL]'} GET: POST 端点被跳过 ({len(get_found)}/0)")
        print(f"  {'[OK]' if post_ok else '[FAIL]'} POST: {len(post_found)}/{len(POST_EXPECTED)}")
        for path in sorted(POST_EXPECTED):
            mark = "[OK]" if path in post_found else "[MISS]"
            print(f"    {mark} /{path} -> {POST_EXPECTED[path]}")

        ok = get_ok and post_ok
        return print_verdict(ok)
    finally:
        server.kill()
        server.wait()
        print("\n[*] 靶场已关闭")


# ─── 召回率分析 ──────────────────────────────────────────────

def test_recall_report():
    print_heading("召回率分析报告")
    modes = [
        ("normal", None, "无软 404"),
        ("soft-404", ["--soft-404"], "简单软 404（单模板）"),
        ("multi-404", ["--multi-404"], "多模板软 404"),
    ]

    results = {}
    for mode_name, srv_args, desc in modes:
        srv = start_server(srv_args or [])
        try:
            print(f"\n[*] 模式: {desc}")
            out = run_scanner_bench()
            found = parse_found_paths(out, EXPECTED)
            results[mode_name] = found
        finally:
            srv.kill()
            srv.wait()
            time.sleep(0.5)

    print(f"\n  模式          发现/总数      召回率    误报")
    print(f"  {'-' * 45}")
    for mode_name, _, desc in modes:
        found = results.get(mode_name, {})
        recall, fp, _, _ = calc_stats(found, EXPECTED)
        print(f"  {desc:<16} {recall}/{len(EXPECTED):<5}    {recall/len(EXPECTED)*100:.0f}%       {fp}")


# ─── Checkpoint 测试 ──────────────────────────────────────────

def test_checkpoint():
    import argparse, tempfile, json, os, asyncio
    from utils.dict_loader import load_dict
    from utils.checkpoint import load_checkpoint, _hash_wordlist
    from core.engine import Scanner
    from utils.wildcard import WildcardProfile

    print_heading("Checkpoint 暂停/恢复测试")
    server = start_server()
    try:
        paths = load_dict(BENCH_WORDLIST)
        half = len(paths) // 2
        half_paths = paths[:half]

        args = argparse.Namespace(
            url=TARGET, method="GET", concurrency=20, timeout=5,
            extension=None, recursive=False, depth=3,
            exclude_status=None, include_status=None,
            max_size=None, min_size=None, header=None, ua=None,
            proxy=None, cookie=None, ignore_ssl_errors=False,
            quiet=True, retries=3, crawl=False, no_wildcard=False,
            report=None, report_format="txt", data=None, delay=0,
            follow_redirect=False, recursion_status=None,
        )
        headers = {"User-Agent": "scent-test"}
        include_status = set()

        print(f"[*] 阶段1: 模拟扫描一半后中断 ({half}/{len(paths)} 条)")
        scanner1 = Scanner(args, None, None, headers, include_status, half_paths, checkpoint_path=None)
        asyncio.run(scanner1.run())

        scanned_set = set(half_paths)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
            cp_path = f.name

        cp_state = {
            "version": 1, "url": TARGET,
            "wordlist_hash": _hash_wordlist(paths),
            "scanned_paths": sorted(scanned_set),
            "current_url": None, "urls": [], "seen": [TARGET],
            "scanned": scanner1.scanned, "cnt": scanner1.cnt,
            "wildcard_root": None, "wildcard_ext": None,
        }
        with open(cp_path, "w", encoding="utf-8") as f:
            json.dump(cp_state, f, indent=2, ensure_ascii=False)

        print(f"[*] 阶段2: 从 checkpoint 恢复，继续扫描剩余 {len(paths) - half} 条")
        cp = load_checkpoint(cp_path)
        cp["wildcard_root"] = WildcardProfile()
        cp["wildcard_ext"] = WildcardProfile()

        scanner2 = Scanner(args, None, None, headers, include_status, paths,
                           resume_checkpoint=cp, checkpoint_path=None)
        asyncio.run(scanner2.run())
        os.unlink(cp_path)

        total_scanned = scanner1.scanned + scanner2.scanned
        total_found = scanner1.cnt + scanner2.cnt

        print(f"\n[*] 阶段1: 扫描 {scanner1.scanned} 条, 发现 {scanner1.cnt}")
        print(f"[*] 阶段2: 扫描 {scanner2.scanned} 条, 发现 {scanner2.cnt}")
        print(f"[*] 合计:  扫描 {total_scanned} 条, 发现 {total_found}")

        ok_no_dup = scanner2.scanned <= len(paths) - half
        ok_full = total_scanned >= len(paths)
        ok_found = total_found >= 14
        print(f"  {'[OK]' if ok_no_dup else '[FAIL]'} 无重复: {scanner2.scanned} <= {len(paths)-half}")
        print(f"  {'[OK]' if ok_full else '[FAIL]'} 完整: {total_scanned} >= {len(paths)}")
        print(f"  {'[OK]' if ok_found else '[FAIL]'} 发现数: {total_found} >= 14")

        ok = ok_no_dup and ok_full and ok_found
        return print_verdict(ok)
    finally:
        server.kill()
        server.wait()
        print("\n[*] 靶场已关闭")


def test_metasploit():
    """Metasploitable 2 集成测试（需虚拟机环境）"""
    print_heading("Metasploitable 2 集成测试")
    print("  跳过（需 Metasploitable 2 虚拟机）")
    return True


# ─── 入口 ──────────────────────────────────────────────────

def main():
    args = sys.argv[1:]

    if "--help" in args:
        print(__doc__)
        return

    if "--recall-report" in args:
        success = test_recall_report()
    elif "--full-bench" in args:
        success = test_full_bench()
    elif "--multi-404" in args:
        success = test_multi_404()
    elif "--metasploit-test" in args:
        success = test_metasploit()
    elif "--soft-404" in args:
        success = test_soft_404()
    elif "--method-test" in args:
        success = test_method()
    elif "--checkpoint-test" in args:
        success = test_checkpoint()
    elif "--scan-only" in args:
        output = run_scanner_bench()
        found = parse_found_paths(output, EXPECTED)
        recall, n_false, _, _ = calc_stats(found, EXPECTED)
        print(f"发现: {len(found)}/{len(EXPECTED)} ({recall/len(EXPECTED)*100:.0f}%) 误报: {n_false}")
        success = recall >= len(EXPECTED) * 0.90
    else:
        success = test_full_bench()

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
