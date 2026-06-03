#!/usr/bin/env node

/**
 * Codex CLI 统一入口 — npm wrapper
 *
 * 职责：
 * 1. 检测当前平台与 CPU 架构，生成 Rust target triple
 * 2. 根据 triple 定位对应的平台原生 npm 包（@openai/codex-*）
 * 3. 在 vendor 目录中解析原生 binary 的实际路径
 * 4. 注入托管环境变量并启动子进程
 * 5. 管理子进程生命周期（信号转发、退出码镜像）
 *
 * 这是 OpenAI Codex CLI 的真实 wrapper，与 mini-codex 原型不同：
 * - 它 spawn 的是 Rust 编译的 native binary，而非 Node.js 脚本
 * - binary 路径来自 @openai/codex-* 可选依赖的 vendor 目录
 * - 支持 npm / bun 两种包管理器的全局安装路径解析
 */

import { spawn } from "node:child_process";
import { existsSync, realpathSync } from "fs";
import { createRequire } from "node:module";
import path from "path";
import { fileURLToPath } from "url";

// ESM 下获取 __filename / __dirname 等价物，以及 CJS 风格的 require
const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const require = createRequire(import.meta.url);

/**
 * Rust target triple → npm 平台包名的映射表
 *
 * 每个平台+架构组合对应一个 @openai/codex-* 可选依赖，
 * 其中包含预编译的 Rust native binary。
 */
const PLATFORM_PACKAGE_BY_TARGET = {
  "x86_64-unknown-linux-musl": "@openai/codex-linux-x64",
  "aarch64-unknown-linux-musl": "@openai/codex-linux-arm64",
  "x86_64-apple-darwin": "@openai/codex-darwin-x64",
  "aarch64-apple-darwin": "@openai/codex-darwin-arm64",
  "x86_64-pc-windows-msvc": "@openai/codex-win32-x64",
  "aarch64-pc-windows-msvc": "@openai/codex-win32-arm64",
};

const { platform, arch } = process;

/**
 * 根据 process.platform 和 process.arch 推导 Rust target triple。
 *
 * 支持的组合：
 * - linux/android + x64/arm64
 * - darwin + x64/arm64
 * - win32 + x64/arm64
 */
let targetTriple = null;
switch (platform) {
  case "linux":
  case "android":
    switch (arch) {
      case "x64":
        targetTriple = "x86_64-unknown-linux-musl";
        break;
      case "arm64":
        targetTriple = "aarch64-unknown-linux-musl";
        break;
      default:
        break;
    }
    break;
  case "darwin":
    switch (arch) {
      case "x64":
        targetTriple = "x86_64-apple-darwin";
        break;
      case "arm64":
        targetTriple = "aarch64-apple-darwin";
        break;
      default:
        break;
    }
    break;
  case "win32":
    switch (arch) {
      case "x64":
        targetTriple = "x86_64-pc-windows-msvc";
        break;
      case "arm64":
        targetTriple = "aarch64-pc-windows-msvc";
        break;
      default:
        break;
    }
    break;
  default:
    break;
}

// 平台不支持时直接报错退出，无法继续
if (!targetTriple) {
  throw new Error(`Unsupported platform: ${platform} (${arch})`);
}

// 防御性检查：确保映射表中存在该 triple 对应的包名
const platformPackage = PLATFORM_PACKAGE_BY_TARGET[targetTriple];
if (!platformPackage) {
  throw new Error(`Unsupported target triple: ${targetTriple}`);
}

// Windows 下 binary 带 .exe 后缀
const codexBinaryName = process.platform === "win32" ? "codex.exe" : "codex";

// 本地 vendor 目录（兜底路径，当 npm 全局安装无法解析时使用）
const localVendorRoot = path.join(__dirname, "..", "vendor");

/** 新版 binary 路径：vendor/<triple>/bin/codex */
const packageBinaryPath = (vendorRoot) =>
  path.join(vendorRoot, targetTriple, "bin", codexBinaryName);

/** 旧版 binary 路径（兼容）：vendor/<triple>/codex/codex */
const legacyBinaryPath = (vendorRoot) =>
  path.join(vendorRoot, targetTriple, "codex", codexBinaryName);

/**
 * 在指定的 vendor 根目录下解析原生 binary 及其路径目录。
 *
 * 解析顺序：
 * 1. 新版路径 vendor/<triple>/bin/codex
 * 2. 旧版路径 vendor/<triple>/codex/codex（向后兼容）
 *
 * @param {string} vendorRoot - vendor 目录的绝对路径
 * @returns {{ binaryPath: string, pathDir: string } | null}
 */
function resolveNativePackage(vendorRoot) {
  const packageRoot = path.join(vendorRoot, targetTriple);
  const binaryPath = packageBinaryPath(vendorRoot);
  if (existsSync(binaryPath)) {
    return {
      binaryPath,
      pathDir: path.join(packageRoot, "codex-path"),
    };
  }

  const legacyPath = legacyBinaryPath(vendorRoot);
  if (existsSync(legacyPath)) {
    return {
      binaryPath: legacyPath,
      pathDir: path.join(packageRoot, "path"),
    };
  }

  return null;
}

/**
 * 解析原生 binary 的实际路径。
 *
 * 优先尝试 npm 全局安装路径（通过 require.resolve 定位平台包），
 * 如果失败则回退到本地 vendor 目录（开发/离线场景）。
 */
let nativePackage;
try {
  // 通过 Node 模块解析找到 @openai/codex-* 包的 package.json
  const packageJsonPath = require.resolve(`${platformPackage}/package.json`);
  nativePackage = resolveNativePackage(
    path.join(path.dirname(packageJsonPath), "vendor"),
  );
} catch {
  // 全局包未安装或不可解析 → 尝试本地 vendor 目录
  nativePackage = resolveNativePackage(localVendorRoot);
}

// 两种路径都找不到 binary → 提示用户重新安装
if (!nativePackage) {
  const packageManager = detectPackageManager();
  const updateCommand =
    packageManager === "bun"
      ? "bun install -g @openai/codex@latest"
      : "npm install -g @openai/codex@latest";
  throw new Error(
    `Missing optional dependency ${platformPackage}. Reinstall Codex: ${updateCommand}`,
  );
}

const { binaryPath, pathDir } = nativePackage;

/**
 * 为什么使用异步 spawn 而不是 spawnSync？
 *
 * 异步 spawn 允许 Node.js 在原生 binary 执行期间响应信号
 * （如 Ctrl+C / SIGINT）。这样父进程可以将信号转发给子进程，
 * 确保无论是子进程退出还是父进程收到致命信号，两个进程都以可预测的方式终止。
 */

/**
 * 将额外的目录前置到 PATH 环境变量中。
 *
 * @param {string[]} newDirs - 要前置的目录列表
 * @returns {string} 更新后的 PATH 字符串
 */
function getUpdatedPath(newDirs) {
  const pathSep = process.platform === "win32" ? ";" : ":";
  const existingPath = process.env.PATH || "";
  const updatedPath = [
    ...newDirs,
    ...existingPath.split(pathSep).filter(Boolean),
  ].join(pathSep);
  return updatedPath;
}

/**
 * 启发式检测安装 Codex 的包管理器，用于生成对应的更新命令提示。
 *
 * 检测依据（按优先级）：
 * 1. npm_config_user_agent 环境变量中包含 "bun/"
 * 2. npm_execpath 环境变量路径中包含 "bun"
 * 3. 当前文件路径中包含 .bun/install/global（bun 全局安装特征）
 * 4. 以上都不满足 → 返回 "npm"（user_agent 存在时）或 null
 *
 * @returns {"bun" | "npm" | null}
 */
function detectPackageManager() {
  const userAgent = process.env.npm_config_user_agent || "";
  if (/\bbun\//.test(userAgent)) {
    return "bun";
  }

  const execPath = process.env.npm_execpath || "";
  if (execPath.includes("bun")) {
    return "bun";
  }

  if (
    __dirname.includes(".bun/install/global") ||
    __dirname.includes(".bun\\install\\global")
  ) {
    return "bun";
  }

  return userAgent ? "npm" : null;
}

// 将 codex 的辅助目录前置到 PATH，确保子进程能找到相关工具
const additionalDirs = [];
if (existsSync(pathDir)) {
  additionalDirs.push(pathDir);
}
const updatedPath = getUpdatedPath(additionalDirs);

/**
 * wrapper 注入的环境变量
 *
 * - PATH：前置了 codex 辅助目录
 * - CODEX_MANAGED_BY_NPM / CODEX_MANAGED_BY_BUN：标记安装来源
 * - CODEX_MANAGED_PACKAGE_ROOT：包根目录的绝对路径
 *
 * 继承 process.env 确保用户自己的环境变量也能传递到子进程。
 */
const env = { ...process.env, PATH: updatedPath };
const packageManagerEnvVar =
  detectPackageManager() === "bun"
    ? "CODEX_MANAGED_BY_BUN"
    : "CODEX_MANAGED_BY_NPM";
env[packageManagerEnvVar] = "1";
env.CODEX_MANAGED_PACKAGE_ROOT = realpathSync(path.join(__dirname, ".."));

/**
 * 启动 Rust native binary 子进程
 *
 * - binaryPath：原生可执行文件的绝对路径（Rust 编译产物）
 * - stdio: "inherit"：子进程的 stdin/stdout/stderr 直接继承父进程
 * - 命令行参数原样转发，wrapper 自身不消费任何业务参数
 */
const child = spawn(binaryPath, process.argv.slice(2), {
  stdio: "inherit",
  env,
});

// 子进程启动失败（binary 缺失、不可执行、权限不足等）
child.on("error", (err) => {
  // eslint-disable-next-line no-console
  console.error(err);
  process.exit(1);
});

/**
 * 将父进程收到的终止信号转发给子进程。
 *
 * 覆盖三种常见信号：
 * - SIGINT  (Ctrl+C)
 * - SIGTERM (kill 默认信号)
 * - SIGHUP  (终端关闭)
 *
 * 确保子进程同步退出，避免孤儿进程。
 * 先检查 child.killed 避免重复发送信号。
 */
const forwardSignal = (signal) => {
  if (child.killed) {
    return;
  }
  try {
    child.kill(signal);
  } catch {
    /* ignore */
  }
};

["SIGINT", "SIGTERM", "SIGHUP"].forEach((sig) => {
  process.on(sig, () => forwardSignal(sig));
});

/**
 * 等待子进程退出，并镜像其终止方式到父进程。
 *
 * 用 Promise 封装子进程的 "exit" 事件，使退出处理结构化。
 * Promise resolve 为一个对象，描述子进程的退出方式：
 * - { type: "code", exitCode: number } — 正常退出
 * - { type: "signal", signal: string } — 被信号终止
 *
 * 这样 shell 脚本和其他工具能观察到正确的退出状态。
 */
const childResult = await new Promise((resolve) => {
  child.on("exit", (code, signal) => {
    if (signal) {
      // 子进程被信号杀死
      resolve({ type: "signal", signal });
    } else {
      resolve({ type: "code", exitCode: code ?? 1 });
    }
  });
});

if (childResult.type === "signal") {
  // 父进程用相同信号自杀，这会产生正确的 128 + n 退出码
  process.kill(process.pid, childResult.signal);
} else {
  process.exit(childResult.exitCode);
}
