# Pi 本地技术文档插件

这个插件可以把技术文档下载到本机，让 Pi Coding Agent 在需要时搜索并阅读**指定版本**的 API 文档。
比如，修改 Python 项目时可以先查本地 Python 文档，再根据查到的内容改代码。

文档保存在本地，不会每轮对话自动塞进 AI 上下文；只有搜索摘要和主动读取的章节会提供给模型。
插件不使用向量数据库、Embedding 或常驻服务。

主要特性：

- **严格按版本检索**：从锁文件和依赖声明中识别项目版本（Python、JavaScript、Rust、Go 等，monorepo 子目录可用），
  只返回完全匹配版本的文档，绝不静默改用其他版本。
- **省上下文**：搜索只返回少量摘要，正文按章节分页读取；模型从工具描述中得知已安装哪些文档。
- **多种来源**：HTTPS 压缩包或单文件、本地目录/文件/压缩包、Git 仓库；支持 HTML、Markdown、RST、纯文本，自动过滤 Sphinx 等站点的导航和重复源码。
- **中英文检索**：英文 API 名称使用 FTS5 全文检索，中文关键词使用子串匹配。
- **安全优先**：安装阶段才联网，压缩包逐项校验，不执行项目或文档中的代码。

## 安装要求

- 已安装 [Pi Coding Agent](https://github.com/badlogic/pi-mono)；
插件使用 Pi 自带的 Extension API，无需额外 `npm install`。
- Python 3.11 或更新版本，且 Python 自带的 SQLite 支持 FTS5（多数常见环境默认支持）。
可用 `PI_KNOWLEDGE_PYTHON` 指定解释器。
- Linux 或 macOS。Windows 暂请在 WSL 中使用。
- 只有从 Git 下载文档时才需要安装 Git。

## 安装插件

在本仓库目录中运行：

```bash
# 仅本次启动加载插件
pi --extension ./src/index.ts

# 或安装为 Pi 的本地 package，以后可持久使用
pi install "$PWD"
```

不要只复制 `src/index.ts`：它需要仓库中的 `backend/` 等文件。
安装后插件提供两个检索工具 `local_docs_search`、`local_docs_read`，以及 `/docs` 文档管理命令（`/docs help` 查看用法，支持 Tab 补全）。

## 下载并使用离线文档

仓库提供了 Python 3.12.3 和 3.11.9 的示例来源。
以下命令使用隔离的示例配置和文档库，不会改动你的默认文档库：

```bash
export PI_KNOWLEDGE_CONFIG="$PWD/config/sources.example.json"
export PI_KNOWLEDGE_HOME="$PWD/.validation/store"

# 下载并建立 Python 3.12.3 文档索引（需要联网，仅下载时需要）
python3 backend/knowledge.py install --source python-3.12.3

# 查看已安装文档
python3 backend/knowledge.py list

# 试着搜索并读取一个章节
python3 backend/knowledge.py search --name python --version 3.12.3 --query 'Path.walk' --limit 2
python3 backend/knowledge.py read --id '<上一步结果中的章节ID>' --length 1500
```

也可以启动 Pi 后直接对话，例如：“请核对当前 Python 版本的 `Path.walk` 参数，先查本地文档再修改代码。
”模型会在适当时调用搜索和读取工具。版本无法确认或没有对应版本文档时，插件会提醒，不会悄悄改用其他版本。

Pi 中可通过 `/docs` 管理文档，例如：

```text
/docs sources                         # 查看配置的来源及是否已安装
/docs install python-3.12.3
/docs list
/docs detect                          # 查看当前项目识别出的依赖版本
/docs search python@3.12.3 Path.walk  # 自己试搜一下
/docs update                          # 重新获取全部已安装来源
```

> `install` 会联网下载并建立本地索引；下载完成后搜索和阅读可离线使用。
> 示例 Python 文档包来自 [Python 官方离线文档下载页](https://docs.python.org/3/download.html)，对应固定版本，并非抓取网页。

## 使用自己的文档

编辑 `config/sources.example.json` 的副本，按需添加 URL、压缩包、Git 仓库或本地文件/目录来源，然后用 `install --source <来源id>` 安装。推荐将配置复制到自己的位置，并设置 `PI_KNOWLEDGE_CONFIG`。
更多配置字段、导入方式和管理命令见[文档配置与管理](docs/configuration.md)。

## 插件如何工作

插件只提供按需检索能力：搜索返回少量摘要，读取工具再按章节分页提供正文。
工具描述会引导模型在 API 不确定或版本敏感时查询，但这不是强制拦截机制；模型可能漏查。
详细调用流程和可选项目指令见[Agent 调用流程](docs/agent-workflow.md)。

## 更多信息

- [文档配置与管理](docs/configuration.md)：添加来源、安装、导入、更新和删除文档
- [版本识别与检索说明](docs/versioning.md)：如何选择项目对应版本、搜索和分页读取
- [安全边界与已知限制](docs/security-limitations.md)：来源安全、格式支持及当前限制
- [测试与验证](docs/validation.md)：运行测试及集成验证方式

本项目在 Pi 1.3.0、Node 24.10.0、Python 3.12.3、Linux 环境验证。
插件实现和目录结构见 `src/`、`backend/`、`config/`、`tests/`。运行 `npm test` 执行后端测试，`npm run smoke` 在真实 Pi 中加载插件做冒烟测试。
