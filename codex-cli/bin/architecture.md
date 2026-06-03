# Codex CLI Wrapper 架构流程图

## 总览

```
用户输入
  │
  ▼
┌─────────────────────────────────────────────────────────────┐
│  $ codex [args...]                                          │
│                                                             │
│  npm/bun 全局安装的 bin 链接 ──► codex.js (本文件)            │
└─────────────────────────────────────────────────────────────┘
  │
  │  process.argv.slice(2) 原样转发
  ▼
        ╔═══════════════════════════════════╗
        ║       codex.js  wrapper          ║
        ║                                 ║
        ║  ┌─────────────────────────┐    ║
        ║  │ 1. 平台 & 架构检测       │    ║
        ║  └───────────┬─────────────┘    ║
        ║              │                  ║
        ║  ┌───────────▼─────────────┐    ║
        ║  │ 2. 生成 target triple   │    ║
        ║  └───────────┬─────────────┘    ║
        ║              │                  ║
        ║  ┌───────────▼─────────────┐    ║
        ║  │ 3. 解析 native binary   │    ║
        ║  └───────────┬─────────────┘    ║
        ║              │                  ║
        ║  ┌───────────▼─────────────┐    ║
        ║  │ 4. 注入 env & 启动子进程 │    ║
        ║  └───────────┬─────────────┘    ║
        ║              │                  ║
        ║  ┌───────────▼─────────────┐    ║
        ║  │ 5. 信号转发 & 退出镜像   │    ║
        ║  └─────────────────────────┘    ║
        ╚══════════════════════╤══════════╝
                               │
                               │  spawn(binaryPath, args)
                               ▼
        ╔═══════════════════════════════════╗
        ║   codex (Rust native binary)     ║
        ║   @openai/codex-{platform}-{arch}║
        ║                                 ║
        ║  ┌─────────────────────────┐    ║
        ║  │ CLI 解析 & 命令路由      │    ║
        ║  └─────────────────────────┘    ║
        ║  ┌─────────────────────────┐    ║
        ║  │ Agent Loop / 工具调用    │    ║
        ║  └─────────────────────────┘    ║
        ║  ┌─────────────────────────┐    ║
        ║  │ OpenAI API 通信         │    ║
        ║  └─────────────────────────┘    ║
        ╚═══════════════════════════════════╝
```

---

## 1. 平台检测 → Target Triple

```
process.platform          process.arch
     │                        │
     ├─ "linux"               ├─ "x64"  ──► x86_64-unknown-linux-musl
     ├─ "android"             └─ "arm64" ──► aarch64-unknown-linux-musl
     │
     ├─ "darwin"              ├─ "x64"  ──► x86_64-apple-darwin
     │                        └─ "arm64" ──► aarch64-apple-darwin
     │
     ├─ "win32"               ├─ "x64"  ──► x86_64-pc-windows-msvc
     │                        └─ "arm64" ──► aarch64-pc-windows-msvc
     │
     └─ 其他 ──────────────────────────────► throw Error (不支持)
```

---

## 2. Target Triple → npm 包名

```
target triple                           npm package
────────────────────────────────────    ────────────────────────────
x86_64-unknown-linux-musl       ──►    @openai/codex-linux-x64
aarch64-unknown-linux-musl      ──►    @openai/codex-linux-arm64
x86_64-apple-darwin             ──►    @openai/codex-darwin-x64
aarch64-apple-darwin            ──►    @openai/codex-darwin-arm64
x86_64-pc-windows-msvc          ──►    @openai/codex-win32-x64
aarch64-pc-windows-msvc         ──►    @openai/codex-win32-arm64
```

---

## 3. Native Binary 路径解析

```
require.resolve("@openai/codex-{platform}-{arch}/package.json")
  │
  ├─ 成功 ──► vendor/<triple>/bin/codex     (新版路径)
  │       └─► vendor/<triple>/codex/codex    (旧版路径, 兼容)
  │
  └─ 失败 ──► ../vendor/<triple>/bin/codex   (本地 vendor 兜底)
          └─► ../vendor/<triple>/codex/codex (本地旧版兜底)

两种都找不到 ──► throw Error ("Missing optional dependency ...")
```

### vendor 目录结构

```
codex-cli/
├── bin/
│   └── codex.js          ← 本 wrapper
├── vendor/
│   ├── x86_64-apple-darwin/
│   │   ├── bin/
│   │   │   └── codex      ← Rust native binary (新版)
│   │   ├── codex/
│   │   │   └── codex      ← Rust native binary (旧版, 兼容)
│   │   └── codex-path/    ← 辅助工具目录 → 前置到 PATH
│   ├── aarch64-apple-darwin/
│   │   └── ...
│   └── ...
└── package.json
```

---

## 4. 环境变量注入

```
process.env (继承用户环境)
  │
  ├─ PATH = "<codex-path>;" + 原 PATH
  │         ▲ 前置辅助工具目录
  │
  ├─ CODEX_MANAGED_BY_NPM = "1"  (npm 安装)
  │   或
  │   CODEX_MANAGED_BY_BUN = "1"  (bun 安装)
  │         ▲ 根据 detectPackageManager() 结果选择
  │
  └─ CODEX_MANAGED_PACKAGE_ROOT = "<包根绝对路径>"
            ▲ 用于 runtime 定位 .env 等资源

                    │
                    │  注入到子进程
                    ▼
            spawn(binaryPath, args, { env })
```

---

## 5. 包管理器检测

```
detectPackageManager()
  │
  ├─ npm_config_user_agent 含 "bun/"     ──► "bun"
  ├─ npm_execpath 含 "bun"               ──► "bun"
  ├─ __dirname 含 ".bun/install/global"  ──► "bun"
  │
  └─ 以上都不满足 ──► "npm" (user_agent 存在时)
                  ──► null  (完全无法检测)

用途：生成对应的重新安装提示命令
  "bun" → "bun install -g @openai/codex@latest"
  "npm" → "npm install -g @openai/codex@latest"
```

---

## 6. 子进程生命周期

```
codex.js (父进程)                        codex binary (子进程)
     │                                         │
     │──── spawn(binaryPath, args) ────────────►│ 启动
     │     { stdio: "inherit", env }            │
     │                                         │
     │  ┌─── signal 转发 ───┐                   │
     │  │ SIGINT  (Ctrl+C) │                   │
     │  │ SIGTERM (kill)   │                   │
     │  │ SIGHUP  (终端关闭) │                   │
     │  └──────────────────┘                   │
     │           │                              │
     │           ▼                              │
     │     child.kill(signal) ─────────────────►│ 收到信号
     │                                         │
     │                                         │ 退出
     │                                         │
     │  ◄──── "exit" 事件 (code, signal) ──────│
     │                                         │
     ├─ 正常退出 (code)                         │
     │  └─ process.exit(code)                  │
     │                                         │
     └─ 信号终止 (signal)                       │
        └─ process.kill(pid, signal)            │
           (产生 128 + n 退出码)                 │
```

---

## 7. 完整调用链路（端到端）

```
终端
 │
 │  $ codex "帮我写一段代码"
 │
 ▼
┌─────────────────┐
│   Shell / PATH   │  查找 codex 命令
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  npm bin 链接   │  node_modules/.bin/codex → codex-cli/bin/codex.js
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│   codex.js      │  Node.js wrapper (本文件)
│                 │
│  1. 检测平台     │  darwin + arm64 → aarch64-apple-darwin
│  2. 定位包       │  @openai/codex-darwin-arm64
│  3. 解析 binary  │  vendor/aarch64-apple-darwin/bin/codex
│  4. 注入 env     │  PATH, MANAGED_BY, PACKAGE_ROOT
│  5. spawn 子进程 │  codex binary + [原样参数]
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  codex binary   │  Rust 原生可执行文件
│                 │
│  - 解析 CLI 参数 │
│  - 启动 Agent    │
│  - 调用 API      │
│  - 执行工具      │
│  - 流式输出      │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  终端输出        │  用户看到结果
└─────────────────┘
```

---

## 与 mini-codex 原型的对比

| 维度 | Codex CLI (本文件) | mini-codex (原型) |
|---|---|---|
| **子进程类型** | Rust native binary | Node.js runtime.js |
| **平台包** | @openai/codex-* (可选依赖) | 无，纯 JS |
| **binary 解析** | vendor 目录 + legacy 兼容 | 不适用 |
| **包管理器检测** | npm / bun 双支持 | 仅 npm |
| **环境变量前缀** | `CODEX_*` | `GENERAL_AGENT_*` |
| **退出处理** | Promise 封装 + 结构化结果 | 直接事件回调 |
