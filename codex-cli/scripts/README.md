# npm releases

这个目录放的是 `codex-cli/` 相关的发布和容器辅助脚本。

它不是 Codex CLI 的 Agent 核心代码，也不是用户日常执行 `codex` 命令会直接进入的路径。这里主要解决两类问题：

```text
codex-cli/scripts/
|-- build_npm_package.py  # 组装单个 npm 包，可选 npm pack
|-- init_firewall.sh      # 在容器里收紧出站网络，只允许访问白名单域名
|-- run_in_container.sh   # 启动 codex Docker 容器，并在容器里执行 codex
`-- README.md             # 发布脚本说明
```

整体关系：

```text
npm release flow
  |
  v
repo root scripts/stage_npm_packages.py
  |
  +--> codex-cli/scripts/build_npm_package.py
  |      |
  |      +--> stage @openai/codex meta package
  |      +--> stage platform native packages
  |      +--> optional npm pack
  |
  `--> dist/npm/*.tgz

container sandbox flow
  |
  v
codex-cli/scripts/run_in_container.sh
  |
  +--> docker run codex image
  +--> write /etc/codex/allowed_domains.txt
  +--> call init_firewall.sh inside container
  `--> execute codex --sandbox workspace-write ...
```

Use the staging helper in the repo root to generate npm tarballs for a release. For
example, to stage the CLI, responses proxy, and SDK packages for version `0.6.0`:

```bash
./scripts/stage_npm_packages.py \
  --release-version 0.6.0 \
  --package codex \
  --package codex-responses-api-proxy \
  --package codex-sdk
```

This downloads the required native package archive artifacts, hydrates `vendor/` for
each package, and writes tarballs to `dist/npm/`.

When `--package codex` is provided, the staging helper builds the lightweight
`@openai/codex` meta package plus all platform-native `@openai/codex` variants
that are later published under platform-specific dist-tags.

Direct `build_npm_package.py` invocations are still useful for package-specific
debugging, but native packages expect `--vendor-src` to point at a prehydrated
`vendor/` tree. Release packaging should use `scripts/stage_npm_packages.py`.

## Script roles

- `build_npm_package.py`：底层 npm package builder。它负责把源码、README、`package.json`、`bin/`、`dist/` 或 `vendor/` 拷贝到 staging 目录，并在需要时调用 `npm pack`。
- `run_in_container.sh`：容器运行入口。它用本地工作目录启动一个 `codex` Docker 容器，把目录挂载进去，然后用受限网络和 `workspace-write` sandbox 执行传入命令。
- `init_firewall.sh`：容器内部网络收口脚本。它读取允许访问的域名，解析成 IP，写入 `ipset`，再用 `iptables` 默认阻断其他流量。

## Notes

- 正式 release 应优先使用 repo root 的 `scripts/stage_npm_packages.py`，因为它会统一下载 native artifacts、hydrate `vendor/`，并调用这里的 `build_npm_package.py`。
- 直接调用 `build_npm_package.py` 更适合调试单个包，例如只看某个平台 native package 的 staging 结果。
- `run_in_container.sh` 和 `init_firewall.sh` 依赖 Docker image 名为 `codex`，并假设镜像里已经安装 `codex` 命令、`init_firewall.sh`、`iptables`、`ipset`、`dig` 和 `curl`。
