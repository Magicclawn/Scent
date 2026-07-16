"""检查点持久化：保存/恢复扫描进度
支持 Ctrl+C 暂停，下次 --resume 继续
"""
import base64
import hashlib
import json
import os
import re
import time
from collections import deque


# ─── WildcardProfile 序列化 ──────────────────────────────────

def _serialize_wildcard(profile):
    """WildcardProfile → dict"""
    if profile is None:
        return None

    # fingerprint_counts: dict key 是 tuple (int, str, int, int)
    fp_counts = {}
    for (status, content_type, length_bucket, body_hash), count in profile.fingerprint_counts.items():
        key = f"{status}|{content_type}|{length_bucket}|{body_hash}"
        fp_counts[key] = count

    return {
        "status_codes": list(profile.status_codes),
        "content_lengths": list(profile.content_lengths),
        "content_hashes": list(profile.content_hashes),
        "is_static": profile.is_static,
        "redirect_regex": profile.redirect_regex.pattern if profile.redirect_regex else None,
        "static_tokens": list(profile.static_tokens),
        "static_tokens_ordered": profile._static_tokens,
        "fingerprint_counts": fp_counts,
        "base_content": base64.b64encode(profile.base_content).decode("ascii") if profile.base_content else "",
    }


def _deserialize_wildcard(data):
    """dict → WildcardProfile"""
    from utils.wildcard import WildcardProfile

    profile = WildcardProfile()
    if data is None:
        return profile

    profile.status_codes = set(data.get("status_codes", []))
    profile.content_lengths = set(data.get("content_lengths", []))
    profile.content_hashes = set(data.get("content_hashes", []))
    profile.is_static = data.get("is_static", False)

    pattern = data.get("redirect_regex")
    profile.redirect_regex = re.compile(pattern) if pattern else None

    profile.static_tokens = set(data.get("static_tokens", []))
    profile._static_tokens = data.get("static_tokens_ordered", [])

    fp_counts = {}
    for key, count in data.get("fingerprint_counts", {}).items():
        parts = key.split("|", 3)
        if len(parts) == 4:
            status, content_type, length_bucket, body_hash = parts
            fp_counts[(int(status), content_type, int(length_bucket), int(body_hash))] = count
    profile.fingerprint_counts = fp_counts

    b64 = data.get("base_content", "")
    profile.base_content = base64.b64decode(b64) if b64 else b""

    return profile


# ─── Scanner 序列化 ──────────────────────────────────────────

def save_checkpoint(scanner, checkpoint_path):
    """保存 Scanner 完整状态到 JSON 文件"""
    # 序列化 wildcard profiles
    wildcard_root = _serialize_wildcard(scanner.wildcard_root)
    wildcard_ext = _serialize_wildcard(scanner.wildcard_ext)

    # 当前 URL 信息
    current_url = None
    if scanner.urls:
        current_url = scanner.urls[0]  # peek at front of deque
    elif hasattr(scanner, '_current_url') and scanner._current_url:
        current_url = scanner._current_url

    state = {
        "version": 1,
        "timestamp": time.time(),
        "url": scanner.url,
        "args": {
            "method": scanner.method,
            "depth": scanner.args.depth,
            "recursive": scanner.args.recursive,
            "extension": scanner.args.extension,
            "follow_redirect": scanner.args.follow_redirect,
        },
        "wordlist_hash": _hash_wordlist(scanner.wordlist_paths),
        "scanned_paths": sorted(scanner._scanned_paths) if hasattr(scanner, '_scanned_paths') else [],
        "current_url": list(current_url) if current_url else None,
        "urls": [list(item) for item in scanner.urls],
        "seen": list(scanner.seen),
        "scanned": scanner.scanned,
        "cnt": scanner.cnt,
        "wildcard_root": wildcard_root,
        "wildcard_ext": wildcard_ext,
        "auto_calibrated": [_serialize_fingerprint(fp) for fp in scanner._auto_calibrated],
        "fingerprint_counts": {_serialize_fingerprint(fp): count
                               for fp, count in scanner._fingerprint_counts.items()},
    }

    with open(checkpoint_path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)

    return checkpoint_path


def load_checkpoint(checkpoint_path):
    """从 JSON 文件恢复 Scanner 状态"""
    with open(checkpoint_path, "r", encoding="utf-8") as f:
        state = json.load(f)

    if state.get("version") != 1:
        raise ValueError(f"不支持的 checkpoint 版本: {state.get('version')}")

    # 还原 Python 数据结构
    state["urls"] = deque(tuple(item) for item in state.get("urls", []))
    state["seen"] = set(state.get("seen", []))
    state["scanned_paths"] = set(state.get("scanned_paths", []))
    state["current_url"] = tuple(state["current_url"]) if state.get("current_url") else None

    # 反序列化 wildcard profiles
    state["wildcard_root"] = _deserialize_wildcard(state.get("wildcard_root"))
    state["wildcard_ext"] = _deserialize_wildcard(state.get("wildcard_ext"))

    # 反序列化自动校准状态
    state["auto_calibrated"] = {_deserialize_fingerprint(k)
                                for k in state.get("auto_calibrated", [])}
    state["fingerprint_counts"] = {_deserialize_fingerprint(k): v
                                   for k, v in state.get("fingerprint_counts", {}).items()}

    return state


def cleanup_checkpoint(checkpoint_path):
    """扫描正常结束时删除 checkpoint"""
    try:
        if os.path.exists(checkpoint_path):
            os.remove(checkpoint_path)
    except OSError:
        pass


# ─── 工具函数 ────────────────────────────────────────────────

def _hash_wordlist(paths):
    """对字典内容做 hash，恢复时校验字典是否一致"""
    h = hashlib.sha256()
    for p in sorted(paths):
        h.update(p.encode("utf-8"))
    return h.hexdigest()


def _serialize_fingerprint(fp):
    """tuple (status, content_type, redirect_path, len//64, hash) → str"""
    return "|".join(str(x) for x in fp)


def _deserialize_fingerprint(key):
    """str → tuple (status, content_type, redirect_path, len//64, hash)"""
    parts = key.split("|", 4)
    return (int(parts[0]), parts[1], parts[2], int(parts[3]), int(parts[4]))


def get_default_checkpoint_path(url):
    """从 URL 生成默认 checkpoint 路径"""
    # 提取 host 部分
    host = url.split("://")[-1].split("/")[0].split(":")[0]
    host = host.replace(".", "_").replace(":", "_")
    return f".checkpoint_{host}.json"
