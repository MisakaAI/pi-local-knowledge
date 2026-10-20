# 版本识别与检索说明

插件按项目证据选择**完全匹配**的已安装文档版本，不会为了凑结果静默回退到其他版本。关于模型何时调用检索工具及完整调用流程，见 [Agent 调用流程](agent-workflow.md)。

## 项目版本识别

插件在需要时读取 Pi 当前工作目录（`ctx.cwd`；CLI 可用 `--cwd` 指定），不导入或执行项目代码。当前识别范围如下：

- Python：`uv.lock`、`poetry.lock`、`requirements.txt`、`requirements-dev.txt`、`pyproject.toml` 的标准 `[project]` 依赖；以及 `.python-version`、`.venv/pyvenv.cfg`、`venv/pyvenv.cfg`。
- JavaScript：`package-lock.json` 中根项目直接安装的依赖、`package.json` 的 `dependencies` / `devDependencies`；`.nvmrc` 作为版本声明。
- 只有没有项目证据时，才把可信主机上的 `python3 --version` / `node --version` 作为运行时证据，并明确提醒它不一定是项目实际使用的解释器。

精确版本可以覆盖同一依赖的版本范围；多个精确证据冲突时拒绝选择。只有范围或不完整版本时也不会自动猜测。
必须存在完全相同的已安装文档版本；首版不假设补丁版本或同一 minor 版本之间 API 完全一致。

版本选择不明确时，可以运行：

```bash
python3 backend/knowledge.py detect --cwd /path/to/project
```

也可在 Pi 中执行 `/docs detect`。显式传入搜索 `version` 时必须同时提供 `name`。
显式指定版本代表用户选择了这版文档，**不代表插件已经证明项目兼容**。

当前不自动向上寻找 monorepo 根目录。请在正确子项目启动 Pi，或先人工确认版本。
首版不解析 pnpm/yarn/Bun/Cargo/Go 锁文件、Conda、旧式 Poetry `pyproject.toml`、动态依赖或传递依赖树差异。

## 搜索与读取

搜索使用 SQLite FTS5 关键词 AND 匹配（最多 20 个词），标题和 API 名称权重较高，并优先完整 API 名称的标题命中。
建议用单个 API 名称或少量英文关键词查询，不要把长段自然语言作为搜索词。

默认返回 5 条结果，最多 8 条；每条摘要最多 500 字符。结果保留文档名称、版本、来源、相对路径和章节标题。

读取按章节分页：默认 4000 字符，最多 8000 字符；根据返回的 `next_offset` 继续读取，`null` 表示章节结束。
章节全文保存在本地索引，不会自动全部输出给模型。字符限制可以控制返回大小，但不是模型 Token 的精确限制。

HTML 提取保留函数签名和 `<pre>` 代码缩进；代码块不会被误拆成标题。
RST 仅进行安全的标题/文本提取，不执行 directive 或 include。原始文档快照、来源版本、下载哈希或 Git commit 会保存在库中。

## 结果边界

- 版本不明确、冲突或没有对应版本文档时，工具会告警并拒绝静默回退。
- 无搜索结果不代表 API 不存在；可能是 AND 条件过多、解析范围有限或版本不匹配。可以缩短关键词，再结合源码、类型声明和测试验证。
- 明确版本和来源由配置维护者保证，插件不能自动证明下载内容确实对应其声明版本。
- FTS5 是关键词检索，不支持向量语义或同义词；中文连续文本没有专门分词支持，优先使用 API 名称或英文关键词。
- 文档查询不能代替代码审查和测试。
