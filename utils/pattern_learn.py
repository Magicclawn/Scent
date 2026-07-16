"""反馈驱动变体生成：从命中路径学习后缀/前缀"""

import os

# ─── 后缀列表（按发现顺序尝试）─────────────────────────────────

LEARN_SUFFIXES = [".bak", "~", ".old", ".orig", ".swp", ".swo", ".save", ".backup", ".tmp"]

# ─── 前缀列表 ──────────────────────────────────────────────────

LEARN_PREFIXES = [".", "_", "._", ".ht"]

# ─── 大小写灵敏度 ──────────────────────────────────────────────

class PatternLearner:
    """从已发现的路径中学习，生成值得尝试的变体"""

    def __init__(self):
        # 已命中路径集合 {path, ...}
        self.hit_paths = set()
        # 已命中的后缀, 如 {".bak", "~"}
        self.confirmed_suffixes = set()
        # 已命中的前缀, 如 {"."}
        self.confirmed_prefixes = set()
        # 生成过的变体（防重复）
        self._generated = set()
        # 大小写是否区分（默认区分）
        self.case_sensitive = True

    def on_hit(self, path, status, content_length, content_type):
        """记录一个被确认的路径（非 wildcard、非 404）"""
        self.hit_paths.add(path)

    def _add_if_new(self, path, candidates):
        """添加未生成过的路径到候选列表"""
        if path not in self.hit_paths and path not in self._generated:
            candidates.append(path)
            self._generated.add(path)

    def generate_variants(self, path):
        """为单个命中路径生成变体候选路径列表（纯路径，不含 URL）。

        只返回变体路径，由调用方扫描后确认才计入 hit_paths。
        """
        candidates = []

        # 1. 后缀变换
        for suffix in LEARN_SUFFIXES:
            self._add_if_new(path + suffix, candidates)

        # 2. 前缀变换（只对路径最后一段）
        if "/" in path:
            dir_part, file_part = path.rsplit("/", 1)
            for prefix in LEARN_PREFIXES:
                self._add_if_new(f"{dir_part}/{prefix}{file_part}", candidates)
        else:
            for prefix in LEARN_PREFIXES:
                self._add_if_new(f"{prefix}{path}", candidates)

        # 3. 大小写变换（只对路径最后一段的首字母）
        last_seg = path.rsplit("/", 1)[-1]
        if last_seg and last_seg[0].isalpha():
            flipped = last_seg[0].swapcase() + last_seg[1:]
            if "/" in path:
                case_var = f"{path.rsplit('/', 1)[0]}/{flipped}"
            else:
                case_var = flipped
            self._add_if_new(case_var, candidates)

        return candidates

    def promote_suffix(self, suffix):
        """推广一个验证有效的后缀：为所有已命中路径生成该后缀变体"""
        promoted = []
        for hit_path in self.hit_paths:
            # 只对文件路径加后缀（有扩展名的）
            if "." in hit_path.rsplit("/", 1)[-1]:
                var = hit_path + suffix
                if var not in self.hit_paths and var not in self._generated:
                    promoted.append(var)
                    self._generated.add(var)
        self.confirmed_suffixes.add(suffix)
        return promoted

    def promote_prefix(self, prefix):
        """推广一个验证有效的前缀"""
        promoted = []
        for hit_path in self.hit_paths:
            if "/" in hit_path:
                dir_part, file_part = hit_path.rsplit("/", 1)
                var = f"{dir_part}/{prefix}{file_part}"
            else:
                var = f"{prefix}{hit_path}"
            if var not in self.hit_paths and var not in self._generated:
                promoted.append(var)
                self._generated.add(var)
        self.confirmed_prefixes.add(prefix)
        return promoted
