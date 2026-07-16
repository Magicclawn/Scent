# scent

**feedback-driven web fuzzer**

<br>

![](https://img.shields.io/badge/version-2.9-blue)
![](https://img.shields.io/badge/python-3.10%2B-green)
![](https://img.shields.io/badge/license-MIT-orange)

---

## 为什么选 scent

不是又一个暴力扫描器。反馈驱动——从目标响应中学习，不盲目穷举。

通配符双防线自适应校准、三层分级字典（29K/70K/155K）、扩展名探测、模式学习变体生成、高级过滤 14 参数、MCP Server、响应体 Diff。

---

## 快速开始

```bash
# 默认字典 + 默认并发，零配置
python scent.py -u http://example.com

# 日常快扫
python scent.py -u http://example.com -w dict/quick.txt

# 深度审计
python scent.py -u http://example.com -w dict/full.txt -c 10

# 过滤 404，只看 200/403
python scent.py -u http://example.com --match-status 200,403
```

---

## 安装

```bash
git clone https://github.com/yourname/scent.git
cd scent
pip install -r requirements.txt
```

---

## 核心命令

```
scent -u <url>                 默认快扫
scent -u <url> -e php,html,jsp 扩展名爆破 + 反馈驱动探测
scent -u <url> -r              递归扫描
scent -u <url> --crawl         爬取模式
scent -u <url> --pattern-learn 模式学习变体生成
scent -u <url> --adaptive      自适应速率
```

---

## 字典

| 字典 | 条数 | 共识度 | 用途 |
|------|:---:|:---:|------|
| `dict/quick.txt` | 29,782 | ≥4源 | 快扫（默认） |
| `dict/standard.txt` | 70,271 | ≥3源 | 完整扫 |
| `dict/full.txt` | 155,820 | ≥2源 | 压箱底 |

来源：SecLists + Assetnote + weblist + hfuzz + OneListForAll 等 8 个开源项目，去重清洗后按多源共识分层。

---

## 性能

| 字典 | 本地 | 远程 (100ms RTT) |
|------|:---:|:---:|
| quick (29K) | ~18s | ~2.5min |
| standard (70K) | ~34s | ~6min |
| full (155K) | ~71s | ~13min |

---

## 项目结构

```
scent/
  scent.py            客户端入口
  mcp_server.py        MCP 服务端
  testserver.py        全功能基准靶场 v4 (100+ 路由)
  run_test.py          自动化测试套件
  core/
    engine.py          异步扫描引擎
    scanner.py          单路径扫描器
    config.py            状态码颜色 + Banner
  utils/
    wildcard.py          通配符检测
    filters.py            高级过滤引擎
    pattern_learn.py      模式学习器
    diff.py                响应体 Diff 引擎
    checkpoint.py          暂停/恢复检查点
    ext_probe.py           扩展名探测
    crawl.py                HTML 链接提取
    output.py              多格式报告
    rate_limit.py          自适应速率限制
    dict_loader.py         字典加载
  dict/
    build.py              字典构建脚本
    raw/                    8 个开源原始字典
    quick.txt               三层分级输出
    standard.txt
    full.txt
```

---

## License

MIT
