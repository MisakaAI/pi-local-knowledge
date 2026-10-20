# 文档来源配置与管理

本文介绍如何添加、下载、导入和管理离线文档。快速安装和首次使用见 [README](../README.md)。

## 配置文件与文档库位置

默认来源配置为 `~/.config/pi-local-knowledge/sources.json`；配置文件不存在时插件仍可使用空库。
可通过 `PI_KNOWLEDGE_CONFIG` 或 CLI 的 `--config` 指定配置文件。

文档库位置按以下优先级决定：CLI `--store` > `PI_KNOWLEDGE_HOME` > 配置文件中的 `store` > `~/.local/share/pi-local-knowledge`。

配置文件中的相对 `store` 路径相对于配置文件所在目录；CLI 和环境变量中的相对路径相对于命令的工作目录。
建议使用绝对路径。Pi 后端使用的 Python 可通过 `PI_KNOWLEDGE_PYTHON` 指定可信解释器。

## 来源配置示例

```json
{
  "store": "~/.local/share/pi-local-knowledge",
  "sources": [
    {
      "id": "python-3.12.3",
      "name": "python",
      "version": "3.12.3",
      "type": "url",
      "location": "https://docs.python.org/ftp/python/doc/3.12.3/python-3.12.3-docs-html.tar.bz2",
      "sha256": "1d4646c6f8060e2e3feb99f4552a6ab19aa85b0b6061a37c6bc622a5b36931c5"
    },
    {
      "id": "my-library",
      "name": "my-library",
      "version": "2.4.1",
      "type": "local",
      "location": "./manuals/my-library"
    },
    {
      "id": "flask-3.1.0",
      "name": "flask",
      "version": "3.1.0",
      "type": "git",
      "location": "https://github.com/pallets/flask.git",
      "ref": "3.1.0",
      "subdir": "docs"
    },
    {
      "id": "archive-example",
      "name": "other",
      "version": "1.0.0",
      "type": "archive",
      "location": "./archives/manual.zip",
      "subdir": "docs"
    }
  ]
}
```

| 字段 | 含义 |
|---|---|
| `id` | 来源唯一标识；安装、更新等管理操作使用它 |
| `name` | 文档对应的语言或依赖名，例如 `python`、`flask`；建议小写，Python 包名使用 `-` 而非 `_` |
| `version` | 精确的文档版本。同名不同版本可并存；安装同名同版本会事务性替换 |
| `type` | `url`（HTTPS 压缩包或单文件）、`archive`（本地或 HTTPS 压缩包）、`git`、`local`（本地文件或目录） |
| `location` | URL 或路径；相对路径相对于配置文件目录 |
| `subdir` | 可选，解压/克隆后采用的子目录；相对路径且不允许 `..` |
| `ref` | Git 分支/标签，默认使用 `version`；实际 commit SHA 会记录。需要固定来源时使用受控标签并核对 SHA |
| `sha256` | 可选的下载内容校验值；建议从可信渠道获取并固定 |
| `filename` | URL 单文件没有扩展名时指定文件名，例如 `reference.md` |

支持 `.html`、`.htm`、`.md`、`.markdown`、`.rst`、`.txt`。同一来源可以混合这些格式。

## 安装与管理

```bash
python3 backend/knowledge.py install --source my-library
python3 backend/knowledge.py update --source my-library

# 一次性导入文件、目录或压缩包，不必先修改来源配置
python3 backend/knowledge.py import --name my-library --version 2.4.1 --path /path/to/docs
python3 backend/knowledge.py import --name other --version 1.0.0 --path /path/to/manual.zip

python3 backend/knowledge.py list
python3 backend/knowledge.py detect --cwd /path/to/project
python3 backend/knowledge.py rebuild
python3 backend/knowledge.py remove --name my-library --version 2.4.1
```

全局参数放在 action 前，例如：

```bash
python3 backend/knowledge.py --config /path/to/sources.json --store /tmp/docs install --source project-manual
```

`update` 会重新获取配置中的来源，但不会自动升级 `version`；要安装新版本，需要添加新的配置条目。
一次性 `import` 会保存原路径和明确给定的版本；若要反复更新，建议把来源写进配置，否则再次执行 `import` 即可替换。

CLI 命令输出 JSON；失败时返回非零状态和 `error` 字段。Pi 中的对应管理命令为：

```text
/docs list
/docs detect
/docs install python-3.12.3
/docs update python-3.12.3
/docs import custom 1.0.0 /absolute/path/to/manual
/docs rebuild
/docs remove custom 1.0.0
```

`/docs import` 会把版本之后的剩余文本视为路径，可包含空格，不需要 shell 引号；不展开 `~`，请使用绝对路径。
管理操作由用户命令执行，模型只获得搜索和读取工具，不获得安装/删除工具。自动化场景建议直接使用 Python CLI。

## 更新与存储行为

下载、解析或建立索引失败时，不会替换旧版本。写操作跨进程串行，SQLite 事务确保检索不会看到半套新索引。
已安装文档采用独立快照，删除原导入目录不影响已安装索引。

章节 ID 包含版本和内容摘要；文档更新后旧 ID 可能失效，重新搜索即可。管理命令执行期间不要手动修改库快照。
被强制终止的进程可能留下临时 `stage-*` 或未引用的 `doc-*` 文件；首版没有自动垃圾回收，只有确认数据库未引用后才能手动清理。
