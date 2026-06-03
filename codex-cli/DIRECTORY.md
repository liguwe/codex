# codex-cli 目录作用说明

`codex-cli/` 是 Codex CLI 的 npm 分发入口目录。

它本身不承载 Agent Loop、TUI、工具调用、Approval、Sandbox 等核心业务逻辑。那些主体逻辑在 `codex-rs/` 里，由 Rust 编译成原生可执行文件。`codex-cli/` 的职责更像前端工程里的「npm 包入口壳」或 Node CLI 里的「bin shim」：让用户通过 `npm install -g @openai/codex` 安装一个统一的 `codex` 命令，再由这个命令找到当前平台对应的 Rust binary 并把控制权交给它。

## 目录结构

```text
codex-cli/
|-- package.json
|-- bin/
|   |-- codex.js
|   `-- architecture.md
`-- scripts/
    |-- README.md
    |-- build_npm_package.py
    |-- init_firewall.sh
    `-- run_in_container.sh
```

关键文件：

- `package.json`：声明 npm 包名 `@openai/codex`，并把命令 `codex` 指向 `bin/codex.js`。
- `bin/codex.js`：Node.js wrapper，负责平台检测、native binary 定位、环境变量注入、子进程启动和退出状态转发。
- `bin/architecture.md`：更细的 `codex.js` wrapper 内部流程说明。
- `scripts/build_npm_package.py`：用于构建 npm 包，特别是把预编译 native binary 放进 `vendor/` 结构。
- `scripts/init_firewall.sh` / `scripts/run_in_container.sh`：和容器、网络/防火墙实验环境相关的辅助脚本。

## 总体定位

```text
                  Codex monorepo
                       |
        +--------------+---------------+
        |                              |
        v                              v
  codex-cli/                       codex-rs/
  npm package shell                Rust implementation
        |                              |
        |                              +--> CLI parser
        |                              +--> TUI
        |                              +--> Agent Loop
        |                              +--> Tool / Patch / Shell
        |                              +--> Approval / Sandbox
        |
        +--> publish @openai/codex
        +--> expose `codex` command
        +--> locate native binary
        +--> spawn Rust process
```

从产品链路看，`codex-cli/` 解决的是「用户如何安装和启动 Codex」。`codex-rs/` 解决的是「Codex 启动以后如何作为 Agent 工作」。

## 安装到运行的端到端流程

```text
User
 |
 |  npm install -g @openai/codex
 v
+------------------------------+
| npm global package           |
| @openai/codex                |
|                              |
| package.json                 |
|   bin.codex -> bin/codex.js  |
+---------------+--------------+
                |
                | user runs: codex [args]
                v
+------------------------------+
| codex-cli/bin/codex.js       |
| Node.js wrapper              |
|                              |
| 1. read process.platform     |
| 2. read process.arch         |
| 3. map to Rust target triple |
| 4. map triple to npm package |
| 5. resolve vendor binary     |
| 6. inject env                |
| 7. spawn native binary       |
+---------------+--------------+
                |
                | spawn(binaryPath, originalArgs)
                v
+------------------------------+
| Rust native codex binary     |
| built from codex-rs/         |
|                              |
| - parse CLI args             |
| - load config/session        |
| - start TUI or exec flow     |
| - run Agent Loop             |
| - call tools                 |
| - render result to terminal  |
+------------------------------+
```

## 平台包选择流程

`codex-cli` 不是把所有平台的 Rust binary 都塞进一个包里，而是通过平台相关的 npm 包承载预编译产物。

```text
process.platform + process.arch
        |
        v
+-----------------------------+
| derive Rust target triple   |
+-------------+---------------+
              |
              v
+-----------------------------+
| lookup platform npm package |
+-------------+---------------+
              |
              v
+-----------------------------+
| resolve package vendor dir  |
+-------------+---------------+
              |
              v
+-----------------------------+
| find native codex binary    |
+-------------+---------------+
              |
              v
+-----------------------------+
| spawn binary                |
+-----------------------------+
```

映射关系在 `bin/codex.js` 的 `PLATFORM_PACKAGE_BY_TARGET` 中：

```text
x86_64-unknown-linux-musl   -> @openai/codex-linux-x64
aarch64-unknown-linux-musl  -> @openai/codex-linux-arm64
x86_64-apple-darwin        -> @openai/codex-darwin-x64
aarch64-apple-darwin       -> @openai/codex-darwin-arm64
x86_64-pc-windows-msvc     -> @openai/codex-win32-x64
aarch64-pc-windows-msvc    -> @openai/codex-win32-arm64
```

## wrapper 和 Rust 主体的边界

```text
+--------------------------------------------------+
| codex-cli/bin/codex.js                           |
|--------------------------------------------------|
| - npm command entry                              |
| - platform/arch detection                        |
| - native package resolution                      |
| - PATH and CODEX_* env injection                 |
| - child process lifecycle                        |
| - signal forwarding                              |
+------------------------+-------------------------+
                         |
                         | hand off
                         v
+--------------------------------------------------+
| codex-rs native binary                           |
|--------------------------------------------------|
| - command parsing                                |
| - interactive UI                                 |
| - session/thread/context                         |
| - model client                                   |
| - agent loop                                     |
| - tool registry                                  |
| - shell/file/patch execution                     |
| - approval and sandbox policy                    |
+--------------------------------------------------+
```

这个边界很重要：`codex-cli/` 不是 Codex 的智能核心，而是 Codex 的「安装和启动适配层」。如果要研究 Agent Loop、Tool Registry、Approval、Sandbox，要继续进入 `codex-rs/`；如果要研究一个 Rust CLI 如何被包装成跨平台 npm 命令，就看 `codex-cli/`。

## 对 General Agent CLI 的启发

这个目录可以抽出一个稳定模式：

```text
+-----------------------------+
| lightweight npm package     |
+-------------+---------------+
              |
              v
+-----------------------------+
| platform-aware JS wrapper   |
+-------------+---------------+
              |
              v
+-----------------------------+
| native/runtime implementation|
+-------------+---------------+
              |
              v
+-----------------------------+
| real agent product logic    |
+-----------------------------+
```

对 `General Agent CLI` 来说，这说明入口层可以很薄：

- npm 包负责让用户拿到统一命令。
- wrapper 负责跨平台启动和环境注入。
- 真正的 Agent runtime 可以是 Rust、Node、Bun 或其他实现。
- 安装入口和 Agent 内核应该解耦，避免把业务逻辑塞进 npm shim。

因此，`codex-cli/` 最值得沉淀进原型的是「统一 CLI 命令 -> 平台/运行时定位 -> 子进程托管 -> 退出状态镜像」这条启动链路，而不是 Agent 本身的业务逻辑。
