<!--
README for v0.1.6. Merge only after the v0.1.6 changes have landed and been released.
Every sentence that describes v0.1.6 behaviour is followed by a comment starting "v0.1.6:"; before merging, grep for
"v0.1.6:" and check each one against the released code. "ENGINE-PUBLIC:" marks links that need
Hadeva-Dev/lflabs-memory-engine to be public. Other comments give file:line evidence in this repo at 1c817d5 (CLI
0.1.5) or in the engine wheel lflabs_memory_engine-0.1.3 (paths under lflabs_memory/).
-->
<!-- Simplified Chinese translation of README.md (6fa4b8b). Change it together with README.md and README.ja.md; the
     comments are copied from README.md unchanged. -->

<p align="center"><a href="README.md">English</a> | <b>简体中文</b> | <a href="README.ja.md">日本語</a></p>

<h1 align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/lockup-dark.svg">
    <img src="assets/lockup.svg" alt="Dawnmere" width="340">
  </picture>
</h1>

<p align="center"><b>告诉一个 AI，它们就都知道了。</b><br>
你 Mac 上的一份记忆，由 Claude Code、Codex 和 Cursor 共享。</p>

<p align="center">
  <img src="assets/kip-loop.gif" width="800"
       alt="动画：一张写着“we deploy on Fridays”的便签落进 Claude Code 的水桶，再落入湖中。翠鸟 Kip 把副本衔到 Codex 和 Cursor 的水桶里，每个应用的图标随之亮起。接着有人告诉 Cursor“use pnpm, not npm”，同样的过程再来一遍。">
</p>

```bash
curl -fsSL https://dawnmere.app/install | sh
```

**环境要求：** 搭载 Apple 芯片的 Mac，macOS 14 或更高版本，1 GB 可用磁盘空间，Node.js 18 或更高版本。免费，无需注册账号。<br>
**状态：** 早期测试版（0.1.x）。客户端采用 MIT 许可，引擎源码可见（FSL，两年后转为 MIT）。由 [LF Labs](#who-makes-it-and-the-lf-labs-names) 开发。

<!-- Apple silicon and macOS 14: install.sh:35-38 refuses anything else, and setup.py:73-74 checks macOS again.
     Node 18: connector/package.json "engines" >=18; every app's MCP entry runs `npx -y dawnmere-connector@...`
     (layout.py:11-12, apps.py:43-44, plugin/.mcp.json). 1 GB: setup.py:28,79-81. dawnmere.app/install answers 302 to
     releases/latest/download/install.sh (checked 2026-11-08). -->

## 它能做什么

你把一件值得记住的事告诉某个 AI 应用，Dawnmere 就在你的 Mac 上存一份，其他应用在需要时会自动想起来。在 Claude Code 里用到额度上限、切到 Codex 继续干活时，Codex 已经知道你们周五部署、用的是 pnpm。

```mermaid
flowchart LR
  CC[Claude Code] <--> C
  CX[Codex] <--> C
  CU[Cursor] <--> C
  C["dawnmere-connector<br/>(MCP, one per app)"] <--> D[("Dawnmere on your Mac<br/>one SQLite file, local search")]
```

各应用如何召回和保存记忆：

| 应用 | 召回 | 保存 |
| --- | --- | --- |
| **Claude Code** | 注入每一条提示词，以及会话开始时 | 会话空闲后自动保存（前提是你选了模型）；你输入 "remember that ..." 时；或模型调用 `remember` 时 |
| **Codex** | 注入每一条提示词 | 你输入 "remember that ..." 时，或模型调用 `remember` 时 |
| **Cursor** | 每次新对话开始时 | 模型调用 `remember` 时 |

只能看到工作笔记的应用保存的内容，会被存为工作笔记，所以其他所有应用也都能召回。
<!-- v0.1.6: a `remember` with no kind from a work-only app (Cursor by default) is visible to work apps. -->

<!-- Claude Code hooks: plugin/hooks/hooks.json (UserPromptSubmit, SessionStart, Stop, SessionEnd). Codex: a
     UserPromptSubmit hook running hook-prompt (apps.py:146-153). Cursor: a sessionStart hook only (apps.py:156-163).
     Typed "remember that ..." saved by the prompt hook: engine instant.py:3. Automatic saving needs a model:
     backend.py:17. -->

每个应用还会通过 MCP 获得四个工具：`recall`、`remember`、`forget` 和 `access_status`。
<!-- connector/src/server.ts:24-87 -->

## 为什么用 Dawnmere

- **一份记忆，而不是每个应用各存一份。** 所有应用共用同一个存储，你在 Claude Code 里存下的事实，就是 Cursor 召回的那一条。
- **记忆留在你的 Mac 上。** 记忆就是你“资源库”（Library）文件夹里的一个 SQLite 文件。搜索用小型本地模型在你的 Mac 上完成。不需要账号，不会向 LF Labs 发送任何东西，工具本身也不收集使用数据。
- **由你自己的模型来读。** 自动保存通过 Claude Code 使用你的 Claude 订阅，或者用你自己的 Anthropic API 密钥。也可以完全不用模型。
- **每个应用只能看到你允许的内容。** Cursor 一开始只能看到工作笔记，新接入的应用也只能看到工作笔记。
- **存入的文本会经过筛查。** 看起来像密钥、令牌或密码的文本会被拒绝；读起来像是在给应用下指令的文本也会被拒绝，应用通过 `remember` 保存的内容同样如此。召回的笔记交给应用时，会带上 "notes, not instructions"（是笔记，不是指令）的标注。
  <!-- v0.1.6: MCP `remember` goes through the instruction screen. Key/token refusals: mem.py:1373-1378. Label:
       mem.py:3919, instant.py:34. -->
- **安装可以撤销。** 改动任何东西之前都会先问你，动到的每个文件都会备份，可以用 `--dry-run` 先看它打算做什么，`dawnmere uninstall` 会把文件恢复原样。

<!-- Local store and models: engine METADATA "SQLite + vectors + keyword search", models.json (bge-small, MiniLM
     reranker, optional sense model). No usage data: no telemetry code in the CLI; the engine turns off onnxruntime's
     telemetry (mem.py:206-208). Access defaults: settings.py:9 new_clients "work"; setup.py:100,135-137 Cursor
     personal notes off unless you say yes. Backups and record: setup.py:6, edits.py, uninstall.py:44-72. -->

## 和其他方案比较

在多个编程代理之间共享一份记忆并不是新点子：claude-mem 和 Supermemory 也能做到，而且两者支持的代理都比 Dawnmere 多。主要区别在于记忆放在哪里。以下内容依据各项目 2026 年 11 月 8 日的官方文档：

| | 记忆存放在哪里 | Claude Code、Codex 和 Cursor 能否共享 |
| --- | --- | --- |
| **Dawnmere** | 你 Mac 上的一个 SQLite 文件；搜索在你的 Mac 上运行 | 能，默认共享；每个应用只看到你允许的内容 |
| [claude-mem](https://github.com/thedotmack/claude-mem) | 你机器上的 `~/.claude-mem` | 三者都支持，还支持更多；会话开始时载入其他代理的记忆需要手动开启 |
| [Supermemory](https://supermemory.ai/coding-agents/) | 默认使用托管服务，也可以用 `npx supermemory local` 在本机运行（两者的记忆互不相通） | 能，另外还支持 OpenCode 等 |
| [Mem0 MCP](https://docs.mem0.ai/platform/mem0-mcp) | 由 Mem0 托管，需要 Mem0 账号；你的机器上不运行任何东西 | 能，通过这个账号 |
| 内置记忆 | 项目和主目录里的 [CLAUDE.md 和自动记忆](https://code.claude.com/docs/en/memory)；仓库里的 [AGENTS.md](https://agents.md/) | CLAUDE.md 和自动记忆是 Claude Code 自己的；AGENTS.md 会被 Codex、Cursor 读取，（仓库里没有 CLAUDE.md 时）Claude Code 也会读，但里面是你自己写的指令，不是应用学到的东西 |

如果你只用一个代理，它自带的记忆可能就够用了。Dawnmere 也从这里起步：安装时可以导入 Claude Code 已经存下的笔记。

<!-- Sources, read 2026-11-08: claude-mem README ("Your memory lives in ~/.claude-mem on your machine"; "Works with
     Claude Code, Codex, Cursor, OpenCode and 11 more agents"; CLAUDE_MEM_SESSION_START_INCLUDE_ALL_SOURCES defaults
     to "false"). Supermemory coding-agents page ("a decision saved in Claude Code is there when you open Cursor";
     "Memories don't move between Local and the hosted service"; lists Claude Code, Cursor, Codex, OpenCode, Hermes).
     Mem0 MCP docs ("Nothing runs on your machine: the server is hosted by Mem0"; prerequisites: Mem0 Platform account
     and API key; clients include Claude Code, Codex, Cursor). agents.md lists Codex and Cursor; Claude Code's memory
     docs say it reads AGENTS.md when there is no CLAUDE.md. Import of Claude Code notes: setup.py:103-143. -->

## 安装

```bash
curl -fsSL https://dawnmere.app/install | sh
```

这个地址会跳转到最新 [GitHub release](https://github.com/Hadeva-Dev/dawnmere/releases/latest) 里的 `install.sh`。脚本会：

1. 检查这是不是一台搭载 Apple 芯片、运行 macOS 14 或更高版本的 Mac，不是就停止；
2. 如果你没有较新的 [uv](https://github.com/astral-sh/uv)，就下载 uv 0.12.5，并从 release 下载 `dawnmere` 和引擎的安装包；
3. 用写在脚本里的 sha256 值校验这些文件，只要有一个对不上，就什么都不装；
4. 让 uv 用 Python 3.12 安装它们；引擎依赖的 Python 包从 PyPI 获取，每个都锁定到确切版本并校验 sha256；
   <!-- v0.1.6: dependencies pinned with hashes. Before that, install.sh:110-115 let uv resolve them unpinned. -->
5. 启动 `dawnmere setup`，它在做任何改动之前都会先问你。

如果没有可以提问的终端（比如在脚本里运行），除非传入 `--yes`，否则安装程序会停止：`curl -fsSL https://dawnmere.app/install | sh -s -- --yes`。
<!-- v0.1.6: no-TTY installs require --yes. Check the exact way to pass it. -->

<!-- install.sh:20-22 (uv pin and hash), 33-38 (platform checks), 81-96 (fetch and check), 110-115 (uv tool install
     with --managed-python --python 3.12 and --with the engine wheel). -->

### 先看一遍安装脚本

```bash
curl -fsSL https://dawnmere.app/install -o install.sh
less install.sh
sh install.sh
```

本仓库里的 `install.sh` 是模板：在 release 填入版本号和校验值之前，它不会运行。
<!-- install.sh:10-18, 32 -->

你的应用不依赖 PATH：安装时写入的钩子用完整路径调用 Dawnmere。如果之后终端里找不到 `dawnmere` 命令，把安装程序打印出来的那一行加上，再新开一个终端窗口即可。
<!-- v0.1.6: plugin hooks get absolute paths, and the PATH advice changes. Check the installer's wording. -->

**更新：** 运行 `dawnmere update`，它会用 release 的 `SHA256SUMS` 校验每个文件。重新运行一次安装命令也可以。
<!-- update.py:55-70 -->

## setup 会做什么

`dawnmere setup` 会先列出它要做的事，问你是否继续。然后依次询问：AI 应用该怎么称呼你；后台阅读要不要用你的 Claude 订阅（或者 Anthropic API 密钥，存放在钥匙串里）；Cursor 能不能看到你的个人笔记（默认不能，除非你同意）；以及要不要导入 Claude Code 已经存在 `~/.claude/projects/*/memory` 里的笔记。

之后它会边执行边显示每一步：

| 步骤 | 做了什么 |
| --- | --- |
| Claude Code | 检查 `claude` 是否存在、是否已登录 |
| 搜索模型 | 下载搜索模型（约 310 MB），并校验每个文件的大小和 sha256 |
| 记忆服务 | 启动一个后台服务（LaunchAgent），让搜索保持快速 |
| 你的应用 | 连接已安装的 Claude Code、Codex 和 Cursor |
| 你的笔记 | 导入你在 Claude Code 里的笔记 |
| 自检 | 存一条测试记忆，用 Codex 和 Cursor 的方式把它找出来，然后删掉 |

最后会显示 "Dawnmere is on."。setup 改动的每个文件都会先在旁边复制一份（`<file>.lflabs-backup-<time>`）并记录下来，`dawnmere uninstall` 就能把它恢复。setup 可以随时重新运行，比如以后想加上模型的时候。

- `dawnmere setup --dry-run` 会打印它要做的每一项改动，但什么都不改。
- `dawnmere setup --backend none` 不用模型运行：召回和 remember 照常可用，自动保存关闭。

<!-- Questions: setup.py:103-143. Models: models.json totals 310.2 MB (embed 34.7, rerank 23.9, sense 251.6; sense
     is skipped below 2 GB free, setup.py:29,226). Checks: models.py:60. Self-check: setup.py:407-408.
     "Dawnmere is on.": screen.py:524,581. Backups: layout.py:17. -->

## 你的应用

- **Claude Code**（2.1.301 或更高版本）：setup 会从本仓库安装 `lflabs-memory` 插件，版本与你安装的 release 一致，插件会加上这些工具和四个钩子。如果插件装不上，它会改用 `claude mcp add` 添加同样的工具，并把钩子写入 `~/.claude/settings.json`。
  <!-- v0.1.6: the plugin pins to the release tag. -->
- **Codex**：在 `~/.codex/config.toml` 中添加 `[mcp_servers.lflabs-memory]`，并在 `~/.codex/hooks.json` 中添加一个提示词钩子。在 Codex 里输入一次 `/hooks`，信任这个钩子。
- **Cursor**：在 `~/.cursor/mcp.json` 中添加 `lflabs-memory`，在 `~/.cursor/hooks.json` 中添加一个会话开始钩子，然后重启 Cursor。在你运行 `dawnmere access cursor everything` 之前，Cursor 只能看到工作笔记；`dawnmere access cursor work` 可以再收回来。
- **Claude Desktop 和其他 MCP 应用**：setup 不会连接它们。Claude Desktop 可以打开 [最新 release](https://github.com/Hadeva-Dev/dawnmere/releases/latest) 里的 `dawnmere-connector.mcpb`，或者把下面这段加到 `~/Library/Application Support/Claude/claude_desktop_config.json`：

  ```json
  {
    "mcpServers": {
      "lflabs-memory": {
        "command": "npx",
        "args": ["-y", "dawnmere-connector@0.1.0"]
      }
    }
  }
  ```

  <!-- v0.1.6: check the connector version still matches layout.py CONNECTOR_VERSION. -->
  Windsurf、Gemini CLI 等应用的配置写在 [连接器的 README](connector/README.md) 里。

<!-- MIN_CLAUDE layout.py:20. Plugin then fallback: setup.py:294-313. Codex: apps.py:100-116, 146-153; hint
     apps.py:27. Cursor: apps.py:156-163, access.py:18-21, 124-126. The .mcpb is a release asset. -->

## 命令

| 命令 | 作用 |
| --- | --- |
| `dawnmere setup` | 把你的应用连接到这台 Mac 上的同一份记忆 |
| `dawnmere doctor` | 检查一切是否正常（包括 Node.js），每项检查一行，并给出每个问题的处理办法 |
| `dawnmere export` | 把记忆导出到 `~/Downloads/dawnmere-export-<date>.json`（加 `--format md` 导出为 Markdown） |
| `dawnmere import FILE` | 从导出文件中添加记忆，已有的会跳过 |
| `dawnmere access APP [LEVEL]` | 查看或修改某个应用能看到的范围：`everything`、`nothing-personal`、`work` 或 `nothing`（在这里只能放宽 Cursor） |
| `dawnmere update` | 安装最新 release，并用它的校验值校验 |
| `dawnmere uninstall` | 移除 setup 添加的一切 |

<!-- v0.1.6: doctor checks Node. Commands: main.py:76-131. Export path: export.py:79. Import skips duplicates:
     export.py:112-134. Levels and widening: access.py:18, 124-126. -->

`dawnmere doctor --report` 只输出计数（不含记忆内容、名字或路径），可以放心贴到 issue 里。
<!-- doctor.py:274-297 -->

## 遗忘

应用调用 `forget` 时，这条记忆会从你 Mac 上的数据库中删除，无法找回。`dawnmere uninstall` 也可以删除全部记忆（会先问你）。
<!-- v0.1.6: forget is a real delete. Before that it was a soft delete with `lflabs-memory purge` and `restore`
     (mem.py:1787-1790, 1954-1973). -->

## 哪些东西会离开你的 Mac

你的记忆不会被上传，也不会向 LF Labs 发送任何东西。只有下面这些网络请求：

- **后台阅读**（如果你选了模型）：Claude Code 会话空闲后，这段对话会发给你自己的模型提供方（通过 Claude Code 使用你的 Claude 订阅，或用你的密钥调用 Anthropic API），用来挑出值得记住的内容。每天最多 200 次调用。
- **下载**：uv、Python 和引擎依赖的 Python 包（来自 GitHub 和 PyPI）；搜索模型和 Claude Code 插件（来自本仓库及其 release）；连接器（应用启动它时从 npm 获取）。`dawnmere update` 会向 GitHub 查询最新 release。
- **setup 检查模型**：向 Claude Code 或 Anthropic API 发一次简短的测试调用。

每个应用发给它自己模型的内容由它自己决定，其中也包括它从记忆中召回的内容。

<!-- 200 a day: settings.py:8. Ping: backend.py:59-104. Models URL: THIRD_PARTY.md and models.json. -->

## 卸载

```bash
dawnmere uninstall
```

它会停止并移除后台服务，把记忆从 Claude Code、Codex 和 Cursor 中撤出（把每个文件恢复原样；如果你后来改过那个文件，就只移除 Dawnmere 的条目），从钥匙串中删除 API 密钥，并移除 `dawnmere` 和引擎程序。删除记忆之前它一定会先问你，删除后无法找回；回答“否”或者加上 `--keep-data` 就能保留。setup 做的备份会留在各个文件旁边，卸载时会把它们列出来。

<!-- uninstall.py:44-140 -->

<a id="who-makes-it-and-the-lf-labs-names"></a>
## 谁在做，以及 LF Labs 这个名字

Dawnmere 由 LF Labs（GitHub 上的 [Hadeva-Dev](https://github.com/Hadeva-Dev) 组织）开发。程序内部使用 LF Labs 这个名字，所以下面这些都是 Dawnmere：

| 是什么 | 在哪里 |
| --- | --- |
| 你的记忆、设置和模型 | `~/Library/Application Support/LF Labs/Memory/`（只有你能读取） |
| 服务日志 | `~/Library/Logs/LF Labs/memory.log` |
| 后台服务 | `~/Library/LaunchAgents/com.lflabs.memory.plist` |
| MCP 服务器 id 和 Claude Code 插件 | `lflabs-memory`（插件 `lflabs-memory@lflabs`） |
| 程序 | `~/.local/share/uv/tools/lflabs-memory-cli/`，链接为 `~/.local/bin/dawnmere` 和 `lflabs-memory` |
| Anthropic API 密钥（如果你提供了） | 你的登录钥匙串，名称为 "LF Labs Memory" |

<!-- layout.py:9-16, 33-56; setup.py:462-463 (0700 data folder). -->

## 限制

- **只支持 Mac**：Apple 芯片，macOS 14 或更高版本。引擎用的 ONNX 运行时没有 Intel Mac 版本，也没有 Linux 或 Windows 版。
- **只限一台 Mac。** 不在多台机器之间同步，也没有团队共享记忆。
- **从 Claude Code 保存效果最好。** 在 Codex 里要说 "remember that ..."；在 Cursor 里得由模型调用 `remember`。只有运行 `dawnmere setup --codex-sessions` 之后，才会读取 Codex 自己的会话文件。
- **筛查是自动的，也会有漏网之鱼。** 用 `dawnmere export` 检查一下应用都存了什么。
- **早期测试版。** 版本靠手动发布，更新也很频繁；更新前请先看 [release notes](https://github.com/Hadeva-Dev/dawnmere/releases)。

<!-- Intel: install.sh:37 comment. Releases by hand: RELEASING.md line 3. -->

## 许可证

本仓库中的安装程序、`dawnmere` 命令、Claude Code 插件和连接器采用 MIT 许可（[LICENSE](LICENSE)）。[引擎](https://github.com/Hadeva-Dev/lflabs-memory-engine)以 [Functional Source License 1.1, MIT future license](https://github.com/Hadeva-Dev/lflabs-memory-engine/blob/main/LICENSE)（FSL-1.1-MIT）公开源码：每个版本在发布两年后转为 MIT 许可。搜索模型保留各自的许可证（见 `dawnmere doctor --licenses` 和 [THIRD_PARTY.md](THIRD_PARTY.md)）。

<!-- ENGINE-PUBLIC: both engine links need Hadeva-Dev/lflabs-memory-engine public, with LICENSE at the root of main.
     Engine license: wheel METADATA "License-Expression: FSL-1.1-MIT". -->

## 相关项目

[memory-bench](https://github.com/Hadeva-Dev/memory-bench) 是一个面向助手记忆的开放基准测试，出自同一批人之手。它目前还没有 Dawnmere 的数据行；里面维护者自己的那一行是一个相关的系统，基准测试里也写明了这一点。

发现 bug？请[提交 issue](https://github.com/Hadeva-Dev/dawnmere/issues/new/choose)，并附上 `dawnmere doctor --report` 的输出。安全问题请按 [SECURITY.md](SECURITY.md) 私下报告。
