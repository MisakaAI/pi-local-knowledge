# 实际验证记录

## 环境

- 工作目录：`~/pi-local-knowledge`
- Pi CLI：`1.3.0`
- Node：`v24.10.0`
- Python：`3.12.3`，SQLite FTS5 可用
- 系统：Linux，POSIX 文件锁

按用户提供的 `local-knowledge/pi/extensions.md` 及当前已安装 Pi 的
 `docs/extensions.md`、`docs/packages.md`、`docs/sdk.md` 和官方示例核对接口。
 未修改 Pi 核心源码，未安装额外运行时库。

## 1. 自动化测试

`npm test`：**13/13 通过**（约 0.3 秒，临时目录隔离，不联网）。

覆盖：

- 本地混合 Markdown/RST/HTML/纯文本导入和检索；ZIP、tar.gz 解压。
- HTML API 签名/缩进/代码注释保留；script/nav 排除。
- 多版本严格选择、显式选择警告、缺少精确版本不回退。
- uv/npm 锁文件、pyproject 范围、requirements 精确版本与冲突、虚拟环境版本及 `.nvmrc`；拒绝执行项目提供的 PATH 包装器。
- 小摘要、硬读取上限、超过 16000 字符章节完整分页。
- 断网模拟下搜索/读取/重建；删除后旧 ID 拒绝。
- import、更新后的新内容、旧快照清理、空文档更新失败保留旧索引；两个独立 CLI 进程并发更新正确串行。
- 缺少来源、无效查询、无效 offset、未知章节/版本等常见错误。
- ZipSlip、绝对路径、Windows 盘符/反斜线路径、压缩包链接及本地软链接拒绝；校验值失败与文件限额。

`python3 -m compileall -q backend tests`：通过。

## 2. 真正下载 Python 官方离线文档

从官方具体版本 URL 下载并实际解析、建立 FTS5 索引，而非只下载单页或使用测试替身：

| 文档 | 实际包 SHA256 | 最终章节数 |
|---|---|---:|
| Python 3.12.3 HTML tar.bz2 | `1d4646c6f8060e2e3feb99f4552a6ab19aa85b0b6061a37c6bc622a5b36931c5` | 21448 |
| Python 3.11.9 HTML tar.bz2 | `660a56d8349491f74650a28e3520019f9385b9ee9fd154a45e3dad396e3426df` | 21368 |

查询 `Path.walk` 的第一条命中：

```text
python@3.12.3
python-3.12.3-docs-html/library/pathlib.html
Path.walk(top_down=True, on_error=None, follow_symlinks=False)¶
```

完整章节 4135 字符；每次限定 500 字符，通过 `next_offset` 共 9 页完整读取，包含示例及 `New in version 3.12.`。
同次单条搜索 JSON 约 685 字符，而不是整份 pathlib 文档。

真实数据验收曾发现 HTML `<pre>` 内 `#` 注释被错误识别为标题，截断后续示例及版本说明。
现通过代码块围栏修复，并纳入自动化回归测试。这也是在真实文档上反复重建而非停留于初次原型的修复记录。

## 3. 真实跨版本与离线验证

执行：

```bash
python3 tests/real-docs.py --store config/.validation/store
```

测试内部禁止 `urllib` 网络访问：

- 项目 `.python-version=3.12.3` → 自动命中 3.12.3 `Path.walk`。
- 改为 `3.11.9` → 所有结果严格来自 3.11.9，没有 3.12 新增的 `Path.walk(...)` 定义。
- 改为未安装的 `3.10.0` → 无结果，明确 `No exact documentation ... No cross-version fallback.`。
- 分页拼接包含完整代码与版本说明。
- Markdown、RST 和 Git 获取的文档均可离线查询。

注意：测试禁止的是检索后端使用的网络访问入口，不是通过系统网络命名空间拔网卡；检索实现没有下载路径调用，所有查询均访问本地 SQLite。

## 4. 不修改核心逻辑接入其他来源

使用同一份 `config/sources.example.json` 实际安装：

- `project-manual`：本地目录中的 Markdown/RST 混合文档，4 个章节，`widget.run`、`widget.close` 查询成功。
- `git-example`：`https://github.com/pallets/flask.git` 的 `3.1.0` 标签，`docs` 子目录，373 个章节。
- 实际记录 Git commit：`ab8149664182b662453a563161aa89013c806dc9`。

获取后离线检索 Flask 3.1.0 文档成功。安装、重建、查询使用完全相同的核心索引逻辑。

## 5. 实际 Pi 环境加载和工具调用

执行：

```bash
PI_KNOWLEDGE_HOME="$PWD/config/.validation/store" \
PI_SDK_PATH=~/.npm/_npx/2453649666e7772c/node_modules/@earendil-works/pi-coding-agent \
node tests/pi-smoke.mjs
```

结果：

- Pi `DefaultResourceLoader` 真正加载 `src/index.ts`，加载错误列表为空。
- `createAgentSession` 中实际注册/激活 `local_docs_search`、`local_docs_read`。
- 调用 Pi 创建的工具包装器（不是手工伪造 ExtensionAPI）搜索 Python 3.12.3 `Path.walk` 成功。
- 再调用读取工具，返回正确版本/来源、500 字符正文、`next_offset=500`、`total_chars=4135`。
- 另外验证未知章节 ID 正确抛错、已取消 AbortSignal 正确终止调用。
- 测试不需要连接模型提供商；没有声称执行付费 LLM 自主选工具的端到端测试。

另外执行 `pi --no-session --extension ./src/index.ts --print '/docs list'`，进程正常退出、无扩展加载错误；
本环境有已配置但未启动的 llama-cpp localhost 服务告警，与本插件无关。工具的实际返回值以 SDK 集成测试为准。

## 保存的数据与复现

实际下载后的离线库保留在 **`config/.validation/store`**（约 218 MiB，包含两版 Python、Flask 及本地示例）。
这是本机验收产物，已通过 `.gitignore` 排除，不作为源码提交。

立即复用：

```bash
export PI_KNOWLEDGE_CONFIG="$PWD/config/sources.example.json"
export PI_KNOWLEDGE_HOME="$PWD/config/.validation/store"
pi --extension ./src/index.ts
```

在新机器可按 README 的安装循环重新下载。网络受限时可以手动获取相同包，再通过 `import --path` 本地导入；检索与重建不依赖联网。

## 限制

详细限制和安全边界见[安全边界与已知限制](security-limitations.md)：严格精确版本而不推断 minor 兼容；非全生态锁文件解析；轻量 RST；非语义搜索；
原生 Windows 写操作未支持；无 OS 级沙箱、Git 硬磁盘配额或自动孤儿快照 GC。
