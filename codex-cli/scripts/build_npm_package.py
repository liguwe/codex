#!/usr/bin/env python3
"""Stage and optionally package Codex npm release artifacts.

这个脚本不是 Codex CLI 的运行入口，而是发布入口：它把 monorepo 里的
源码、package.json 和预编译 native binary 组装进一个临时 staging 目录，
必要时再调用 `npm pack` 产出可发布的 tgz 包。
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
CODEX_CLI_ROOT = SCRIPT_DIR.parent
REPO_ROOT = CODEX_CLI_ROOT.parent
RESPONSES_API_PROXY_NPM_ROOT = REPO_ROOT / "codex-rs" / "responses-api-proxy" / "npm"
CODEX_SDK_ROOT = REPO_ROOT / "sdk" / "typescript"
CODEX_NPM_NAME = "@openai/codex"
CODEX_PACKAGE_COMPONENT = "codex-package"

# Codex 的 npm 发布模型有两层：
#
# 1. `@openai/codex` meta package：
#    只包含 `bin/codex.js`，用户安装和执行的统一入口。
# 2. platform package：
#    每个平台/架构一份，里面放 Rust 编译出来的 native binary。
#
# `npm_name` 是 meta package 里 optionalDependencies 使用的别名，也就是
# `bin/codex.js` 运行时会尝试解析的包名。真正发布到 npm registry 的底层包名
# 仍然是 `@openai/codex`，只是通过不同 prerelease 版本区分平台产物。
CODEX_PLATFORM_PACKAGES: dict[str, dict[str, str]] = {
    "codex-linux-x64": {
        "npm_name": "@openai/codex-linux-x64",
        "npm_tag": "linux-x64",
        "target_triple": "x86_64-unknown-linux-musl",
        "os": "linux",
        "cpu": "x64",
    },
    "codex-linux-arm64": {
        "npm_name": "@openai/codex-linux-arm64",
        "npm_tag": "linux-arm64",
        "target_triple": "aarch64-unknown-linux-musl",
        "os": "linux",
        "cpu": "arm64",
    },
    "codex-darwin-x64": {
        "npm_name": "@openai/codex-darwin-x64",
        "npm_tag": "darwin-x64",
        "target_triple": "x86_64-apple-darwin",
        "os": "darwin",
        "cpu": "x64",
    },
    "codex-darwin-arm64": {
        "npm_name": "@openai/codex-darwin-arm64",
        "npm_tag": "darwin-arm64",
        "target_triple": "aarch64-apple-darwin",
        "os": "darwin",
        "cpu": "arm64",
    },
    "codex-win32-x64": {
        "npm_name": "@openai/codex-win32-x64",
        "npm_tag": "win32-x64",
        "target_triple": "x86_64-pc-windows-msvc",
        "os": "win32",
        "cpu": "x64",
    },
    "codex-win32-arm64": {
        "npm_name": "@openai/codex-win32-arm64",
        "npm_tag": "win32-arm64",
        "target_triple": "aarch64-pc-windows-msvc",
        "os": "win32",
        "cpu": "arm64",
    },
}

# 一次 staging `codex` release 时，实际需要同时准备 meta package 和所有平台包。
PACKAGE_EXPANSIONS: dict[str, list[str]] = {
    "codex": ["codex", *CODEX_PLATFORM_PACKAGES],
}

# 每种 npm 包需要从 vendor tree 中拷贝哪些 native component。
#
# - `codex` meta package 不带 native binary，只声明 optionalDependencies。
# - `codex-<platform>` 平台包拷贝整个 codex-package component。
# - `codex-responses-api-proxy` 只拷贝 proxy 对应的 native component。
# - `codex-sdk` 是 TypeScript SDK，需要本地 build 生成 dist。
PACKAGE_NATIVE_COMPONENTS: dict[str, list[str]] = {
    "codex": [],
    "codex-linux-x64": [CODEX_PACKAGE_COMPONENT],
    "codex-linux-arm64": [CODEX_PACKAGE_COMPONENT],
    "codex-darwin-x64": [CODEX_PACKAGE_COMPONENT],
    "codex-darwin-arm64": [CODEX_PACKAGE_COMPONENT],
    "codex-win32-x64": [CODEX_PACKAGE_COMPONENT],
    "codex-win32-arm64": [CODEX_PACKAGE_COMPONENT],
    "codex-responses-api-proxy": ["codex-responses-api-proxy"],
    "codex-sdk": [],
}

# 平台包只应该包含自己的 target triple，不能把其他平台的 binary 一起打进去。
PACKAGE_TARGET_FILTERS: dict[str, str] = {
    package_name: package_config["target_triple"]
    for package_name, package_config in CODEX_PLATFORM_PACKAGES.items()
}

PACKAGE_CHOICES = tuple(PACKAGE_NATIVE_COMPONENTS)

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build or stage the Codex CLI npm package.")
    parser.add_argument(
        "--package",
        choices=PACKAGE_CHOICES,
        default="codex",
        help="Which npm package to stage (default: codex).",
    )
    parser.add_argument(
        "--version",
        help="Version number to write to package.json inside the staged package.",
    )
    parser.add_argument(
        "--release-version",
        help=(
            "Version to stage for npm release."
        ),
    )
    parser.add_argument(
        "--staging-dir",
        type=Path,
        help=(
            "Directory to stage the package contents. Defaults to a new temporary directory "
            "if omitted. The directory must be empty when provided."
        ),
    )
    parser.add_argument(
        "--tmp",
        dest="staging_dir",
        type=Path,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--pack-output",
        type=Path,
        help="Path where the generated npm tarball should be written.",
    )
    parser.add_argument(
        "--vendor-src",
        type=Path,
        help="Directory containing pre-installed native binaries to bundle (vendor root).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    package = args.package
    version = args.version
    release_version = args.release_version

    # `--release-version` 是 release staging 的语义化参数；如果同时传了
    # `--version`，两者必须一致，避免 staging 包和发布版本发生漂移。
    if release_version:
        if version and version != release_version:
            raise RuntimeError("--version and --release-version must match when both are provided.")
        version = release_version

    if not version:
        raise RuntimeError("Must specify --version or --release-version.")

    staging_dir, created_temp = prepare_staging_dir(args.staging_dir)

    try:
        # 第一步只组装 JS/README/package.json 等普通 npm 包内容。
        stage_sources(staging_dir, version, package)

        vendor_src = args.vendor_src.resolve() if args.vendor_src else None
        native_components = PACKAGE_NATIVE_COMPONENTS.get(package, [])
        target_filter = PACKAGE_TARGET_FILTERS.get(package)

        # 第二步按需把预编译 native binary 从 vendor-src 拷贝进 staging。
        # native 产物通常由更外层的 release/stage 脚本提前下载或构建好。
        if native_components:
            if vendor_src is None:
                components_str = ", ".join(native_components)
                raise RuntimeError(
                    "Native components "
                    f"({components_str}) required for package '{package}'. Provide --vendor-src "
                    "pointing to a directory containing pre-installed binaries."
                )

            copy_native_binaries(
                vendor_src,
                staging_dir,
                native_components,
                target_filter={target_filter} if target_filter else None,
            )

        if release_version:
            staging_dir_str = str(staging_dir)
            # release 模式只 staging，不自动验证；这里打印的是人工 smoke test 命令。
            if package == "codex":
                print(
                    f"Staged version {version} for release in {staging_dir_str}\n\n"
                    "Verify the CLI:\n"
                    f"    node {staging_dir_str}/bin/codex.js --version\n"
                    f"    node {staging_dir_str}/bin/codex.js --help\n\n"
                )
            elif package == "codex-responses-api-proxy":
                print(
                    f"Staged version {version} for release in {staging_dir_str}\n\n"
                    "Verify the responses API proxy:\n"
                    f"    node {staging_dir_str}/bin/codex-responses-api-proxy.js --help\n\n"
                )
            elif package in CODEX_PLATFORM_PACKAGES:
                print(
                    f"Staged version {version} for release in {staging_dir_str}\n\n"
                    "Verify native payload contents:\n"
                    f"    ls {staging_dir_str}/vendor\n\n"
                )
            else:
                print(
                    f"Staged version {version} for release in {staging_dir_str}\n\n"
                    "Verify the SDK contents:\n"
                    f"    ls {staging_dir_str}/dist\n"
                    "    node -e \"import('./dist/index.js').then(() => console.log('ok'))\"\n\n"
                )
        else:
            print(f"Staged package in {staging_dir}")

        if args.pack_output is not None:
            output_path = run_npm_pack(staging_dir, args.pack_output)
            print(f"npm pack output written to {output_path}")
    finally:
        if created_temp:
            # Preserve the staging directory for further inspection.
            pass

    return 0


def prepare_staging_dir(staging_dir: Path | None) -> tuple[Path, bool]:
    """Create or validate the staging directory.

    staging 目录就是即将被 `npm pack` 的包根目录。外部指定目录时要求为空，
    防止旧产物混进新包；未指定时创建临时目录，并故意保留给后续检查。
    """
    if staging_dir is not None:
        staging_dir = staging_dir.resolve()
        staging_dir.mkdir(parents=True, exist_ok=True)
        if any(staging_dir.iterdir()):
            raise RuntimeError(f"Staging directory {staging_dir} is not empty.")
        return staging_dir, False

    temp_dir = Path(tempfile.mkdtemp(prefix="codex-npm-stage-"))
    return temp_dir, True


def stage_sources(staging_dir: Path, version: str, package: str) -> None:
    """Copy package sources into staging and write the final package.json."""
    package_json: dict
    package_json_path: Path | None = None

    if package == "codex":
        # meta package：只带 Node wrapper，不带 native binary。
        bin_dir = staging_dir / "bin"
        bin_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(CODEX_CLI_ROOT / "bin" / "codex.js", bin_dir / "codex.js")

        readme_src = REPO_ROOT / "README.md"
        if readme_src.exists():
            shutil.copy2(readme_src, staging_dir / "README.md")

        package_json_path = CODEX_CLI_ROOT / "package.json"
    elif package in CODEX_PLATFORM_PACKAGES:
        # platform package：只带 vendor native payload，并通过 os/cpu 限制安装平台。
        platform_package = CODEX_PLATFORM_PACKAGES[package]
        platform_npm_tag = platform_package["npm_tag"]
        platform_version = compute_platform_package_version(version, platform_npm_tag)

        readme_src = REPO_ROOT / "README.md"
        if readme_src.exists():
            shutil.copy2(readme_src, staging_dir / "README.md")

        with open(CODEX_CLI_ROOT / "package.json", "r", encoding="utf-8") as fh:
            codex_package_json = json.load(fh)

        package_json = {
            "name": CODEX_NPM_NAME,
            "version": platform_version,
            "license": codex_package_json.get("license", "Apache-2.0"),
            "os": [platform_package["os"]],
            "cpu": [platform_package["cpu"]],
            "files": ["vendor"],
            "repository": codex_package_json.get("repository"),
        }

        engines = codex_package_json.get("engines")
        if isinstance(engines, dict):
            package_json["engines"] = engines

        package_manager = codex_package_json.get("packageManager")
        if isinstance(package_manager, str):
            package_json["packageManager"] = package_manager
    elif package == "codex-responses-api-proxy":
        # responses API proxy 有自己的 npm launcher 和 package.json。
        bin_dir = staging_dir / "bin"
        bin_dir.mkdir(parents=True, exist_ok=True)
        launcher_src = RESPONSES_API_PROXY_NPM_ROOT / "bin" / "codex-responses-api-proxy.js"
        shutil.copy2(launcher_src, bin_dir / "codex-responses-api-proxy.js")

        readme_src = RESPONSES_API_PROXY_NPM_ROOT / "README.md"
        if readme_src.exists():
            shutil.copy2(readme_src, staging_dir / "README.md")

        package_json_path = RESPONSES_API_PROXY_NPM_ROOT / "package.json"
    elif package == "codex-sdk":
        # SDK 发布前需要先跑 TypeScript 构建，把 dist 拷贝进 staging。
        package_json_path = CODEX_SDK_ROOT / "package.json"
        stage_codex_sdk_sources(staging_dir)
    else:
        raise RuntimeError(f"Unknown package '{package}'.")

    if package_json_path is not None:
        with open(package_json_path, "r", encoding="utf-8") as fh:
            package_json = json.load(fh)
        package_json["version"] = version

    if package == "codex":
        # meta package 通过 optionalDependencies 拉取平台 native 包。
        # npm 会根据平台包自己的 os/cpu 字段只安装匹配当前机器的那一份。
        package_json["files"] = ["bin/codex.js"]
        package_json["optionalDependencies"] = {
            CODEX_PLATFORM_PACKAGES[platform_package]["npm_name"]: (
                f"npm:{CODEX_NPM_NAME}@"
                f"{compute_platform_package_version(version, CODEX_PLATFORM_PACKAGES[platform_package]['npm_tag'])}"
            )
            for platform_package in PACKAGE_EXPANSIONS["codex"]
            if platform_package != "codex"
        }

    elif package == "codex-sdk":
        # 发布包里不需要 prepare 脚本，避免用户安装 SDK 时再次触发本地构建。
        scripts = package_json.get("scripts")
        if isinstance(scripts, dict):
            scripts.pop("prepare", None)

        dependencies = package_json.get("dependencies")
        if not isinstance(dependencies, dict):
            dependencies = {}
        dependencies[CODEX_NPM_NAME] = version
        package_json["dependencies"] = dependencies

    with open(staging_dir / "package.json", "w", encoding="utf-8") as out:
        json.dump(package_json, out, indent=2)
        out.write("\n")


def compute_platform_package_version(version: str, platform_tag: str) -> str:
    # npm forbids republishing the same package name/version, so each
    # platform-specific tarball needs a unique version string.
    return f"{version}-{platform_tag}"


def run_command(cmd: list[str], cwd: Path | None = None) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=cwd, check=True)


def stage_codex_sdk_sources(staging_dir: Path) -> None:
    """Build the TypeScript SDK and copy its publishable files."""
    package_root = CODEX_SDK_ROOT

    run_command(["pnpm", "install", "--frozen-lockfile"], cwd=package_root)
    run_command(["pnpm", "run", "build"], cwd=package_root)

    dist_src = package_root / "dist"
    if not dist_src.exists():
        raise RuntimeError("codex-sdk build did not produce a dist directory.")

    shutil.copytree(dist_src, staging_dir / "dist")

    readme_src = package_root / "README.md"
    if readme_src.exists():
        shutil.copy2(readme_src, staging_dir / "README.md")

    license_src = REPO_ROOT / "LICENSE"
    if license_src.exists():
        shutil.copy2(license_src, staging_dir / "LICENSE")


def copy_native_binaries(
    vendor_src: Path,
    staging_dir: Path,
    components: list[str],
    target_filter: set[str] | None = None,
) -> None:
    """Copy requested native components from a hydrated vendor tree.

    `vendor_src` 的形状大致是：

        vendor/
          <target-triple>/
            codex-package/
            codex-responses-api-proxy/

    当 component 是 `codex-package` 时，整个平台 target 目录都会被拷贝；
    其他 component 则只拷贝目标 component 子目录。
    """
    vendor_src = vendor_src.resolve()
    if not vendor_src.exists():
        raise RuntimeError(f"Vendor source directory not found: {vendor_src}")

    components_set = set(components)
    if not components_set:
        return

    vendor_dest = staging_dir / "vendor"
    if vendor_dest.exists():
        shutil.rmtree(vendor_dest)
    vendor_dest.mkdir(parents=True, exist_ok=True)

    copied_targets: set[str] = set()

    for target_dir in vendor_src.iterdir():
        if not target_dir.is_dir():
            continue

        if target_filter is not None and target_dir.name not in target_filter:
            continue

        copied_targets.add(target_dir.name)

        dest_target_dir = vendor_dest / target_dir.name

        # codex platform package 需要保留 target 目录下的完整 native payload。
        if CODEX_PACKAGE_COMPONENT in components_set:
            if dest_target_dir.exists():
                shutil.rmtree(dest_target_dir)
            shutil.copytree(target_dir, dest_target_dir)
        else:
            dest_target_dir.mkdir(parents=True, exist_ok=True)

        # 非 codex-package 的 component 只按名称精确拷贝。
        for component in sorted(components_set - {CODEX_PACKAGE_COMPONENT}):
            src_component_dir = target_dir / component
            if not src_component_dir.exists():
                raise RuntimeError(
                    f"Missing native component '{component}' in vendor source: {src_component_dir}"
                )

            dest_component_dir = dest_target_dir / component
            if dest_component_dir.exists():
                shutil.rmtree(dest_component_dir)
            shutil.copytree(src_component_dir, dest_component_dir)

    if target_filter is not None:
        # 平台包必须命中自己的 target，否则会发布出缺 binary 的 npm 包。
        missing_targets = sorted(target_filter - copied_targets)
        if missing_targets:
            missing_list = ", ".join(missing_targets)
            raise RuntimeError(f"Missing target directories in vendor source: {missing_list}")


def run_npm_pack(staging_dir: Path, output_path: Path) -> Path:
    """Run `npm pack` against the staged package and move the tarball to output_path."""
    output_path = output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="codex-npm-pack-") as pack_dir_str:
        pack_dir = Path(pack_dir_str)
        # 使用独立 npm cache/log 目录，避免 release packaging 被用户本机 npm 状态污染。
        npm_cache_dir = pack_dir / "npm-cache"
        npm_logs_dir = pack_dir / "npm-logs"
        npm_cache_dir.mkdir()
        npm_logs_dir.mkdir()
        env = os.environ.copy()
        env["NPM_CONFIG_CACHE"] = str(npm_cache_dir)
        env["NPM_CONFIG_LOGS_DIR"] = str(npm_logs_dir)
        stdout = subprocess.check_output(
            ["npm", "pack", "--json", "--pack-destination", str(pack_dir)],
            cwd=staging_dir,
            env=env,
            text=True,
        )
        try:
            pack_output = json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Failed to parse npm pack output.") from exc

        if not pack_output:
            raise RuntimeError("npm pack did not produce an output tarball.")

        tarball_name = pack_output[0].get("filename") or pack_output[0].get("name")
        if not tarball_name:
            raise RuntimeError("Unable to determine npm pack output filename.")

        tarball_path = pack_dir / tarball_name
        if not tarball_path.exists():
            raise RuntimeError(f"Expected npm pack output not found: {tarball_path}")

        shutil.move(str(tarball_path), output_path)

    return output_path


if __name__ == "__main__":
    import sys

    sys.exit(main())
