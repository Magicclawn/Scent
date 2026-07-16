"""字典加载器：读取 wordlist 文件"""
import sys

def load_dict(dict_path, exts=None):
    """读取字典文件，返回路径列表"""
    paths = []
    try:
        with open(dict_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if exts and "%EXT%" in line:
                    for ext in exts:
                        paths.append(line.replace("%EXT%", ext.lstrip(".")))
                else:
                    paths.append(line)
    except FileNotFoundError:
        print(f"[-] 字典文件不存在: {dict_path}")
        sys.exit(1)
    return paths

