# 版本识别与检索说明

插件按项目证据选择**完全匹配**的已安装文档版本，不会为了凑结果静默回退到其他版本。关于模型何时调用检索工具及完整调用流程，见 [Agent 调用流程](agent-workflow.md)。

## 项目版本识别

插件在需要时读取 Pi 当前工作目录（`ctx.cwd`；CLI 可用 `--cwd` 指定），不导入或执行项目代码。
如果工作目录位于 Git 仓库中，还会依次读取上级目录直到仓库根目录（最多 12 层）；不在 Git 仓库中时只读取工作目录本身。

| 生态 | 识别的文件 |
|---|---|
| Python | `uv.lock`、`poetry.lock`、`Pipfile.lock`、`requirements.txt`、`requirements-dev.txt`、`pyproject.toml`（标准 `[project]` 依赖与 `requires-python`，以及 Poetry 的 `[tool.poetry.*dependencies]`）；运行时：`.python-version`、`.venv/pyvenv.cfg`、`venv/pyvenv.cfg` |
| JavaScript | `package-lock.json`（根项目直接安装的依赖）、`yarn.lock`（Classic 与 Berry）、`pnpm-lock.yaml`（根 importer 的直接依赖）、`package.json` 的 `dependencies` / `devDependencies` / `optionalDependencies`；运行时：`.nvmrc`、`.node-version`、`engines.node`（范围） |
| Rust | `Cargo.lock`；工具链：`rust-toolchain.toml`、`rust-toolchain` |
| Go | `go.mod` 的 `require`、`go` 与 `toolchain` 指令 |
| 通用 | asdf/mise 的 `.tool-versions`（`python`、`nodejs`、`golang`、`rust` 等） |

- `yarn.lock` 可能为同一包记录多个版本；插件只采用 `package.json` 中直接依赖的版本范围所解析到的那一条。
- 依赖名比较时忽略大小写，并把 `-`、`_`、`.` 视为相同（PEP 503 规则），文档名称同样处理。
- 只有没有项目证据时，才把可信主机上的 `python3 --version` / `node --version` 作为运行时证据，并明确提醒它不一定是项目实际使用的解释器。
位于项目目录内部的可执行文件（如 `.venv/bin/python3` 或项目提供的包装脚本）不会被执行。
- 无法解析的文件（损坏的 JSON/TOML 等）会被跳过，并在搜索 `warnings` 和 `/docs detect` 的 `problems` 中提示，不会导致搜索失败。

精确版本可以覆盖同一依赖的版本范围；同一目录层级中多个精确证据冲突时拒绝选择。
不同目录层级都有精确证据时，**离工作目录最近的一层优先**（子包覆盖仓库根目录）。
只有范围或不完整版本时也不会自动猜测。
必须存在完全相同的已安装文档版本；插件不假设补丁版本或同一 minor 版本之间 API 完全一致。

版本选择不明确时，可以运行：

```bash
python3 backend/knowledge.py detect --cwd /path/to/project
```

输出包含识别出的项目根目录 `project_root`、证据列表 `evidence`（每条带来源文件，如 `../package-lock.json`）以及 `problems`。
也可在 Pi 中执行 `/docs detect`。显式传入搜索 `version` 时必须同时提供 `name`；此时不会读取项目文件。
显式指定版本代表用户选择了这版文档，**不代表插件已经证明项目兼容**。

目前不解析 Bun 锁文件、Conda 环境、动态依赖或传递依赖树差异；`pnpm-lock.yaml` 只读取根 importer。

## 搜索与读取

搜索使用 SQLite FTS5 关键词 AND 匹配（最多 20 个词），标题和 API 名称权重较高，并优先完整 API 名称的标题命中。
没有章节同时包含全部关键词时，会自动改为匹配任一关键词，返回 `match: "any"` 并给出告警。
关键词包含中文、日文或韩文时，改为按子串扫描对应版本的章节（标题命中优先），因此 `表格 排序` 这类查询也能命中。
建议用单个 API 名称或少量关键词查询，不要把长段自然语言作为搜索词。

未指定 `name` 时，只搜索项目声明了版本的文档；项目未声明的文档会汇总成一条告警，提示传入 `name` 和 `version`。

默认返回 5 条结果，最多 8 条；每条摘要最多 500 字符。结果保留文档名称、版本、相对路径和章节标题，
`searched` 列出实际搜索的文档版本，来源按文档版本汇总在 `sources` 中。

读取按章节分页：默认 4000 字符，最多 8000 字符；根据返回的 `next_offset` 继续读取，`null` 表示章节结束。
章节全文保存在本地索引，不会自动全部输出给模型。字符限制可以控制返回大小，但不是模型 Token 的精确限制。

HTML 提取保留函数签名、`<pre>` 代码缩进和表格单元格分隔；代码块不会被误拆成标题。
Sphinx、MkDocs、Docusaurus 等生成的侧边栏、导航、页眉页脚和标题后的 `¶` 永久链接不会进入索引。
Markdown 支持 ATX（`#`）与 Setext（`===` / `---` 下划线）标题，并忽略开头的 YAML front matter。
RST 支持只有下划线和上下双线两种标题样式。
RST 仅进行安全的标题/文本提取，不执行 directive 或 include。原始文档快照、来源版本、下载哈希或 Git commit 会保存在库中。

## 结果边界

- 版本不明确、冲突或没有对应版本文档时，工具会告警并拒绝静默回退。
- 无搜索结果不代表 API 不存在；可能是 AND 条件过多、解析范围有限或版本不匹配。可以缩短关键词，再结合源码、类型声明和测试验证。
- 明确版本和来源由配置维护者保证，插件不能自动证明下载内容确实对应其声明版本。
- FTS5 是关键词检索，不支持向量语义或同义词；中文按子串匹配，没有分词和相关度排序，优先使用 API 名称或较具体的词。
- 文档查询不能代替代码审查和测试。
