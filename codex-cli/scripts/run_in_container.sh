#!/bin/bash
set -e

# 这个脚本用于把一次 Codex CLI 执行放进 Docker 容器里跑。
#
# 它做的事：
# 1. 选定本地工作目录，并把它挂载进容器。
# 2. 启动名为 `codex` 的 Docker image。
# 3. 把允许联网的域名写入容器内 `/etc/codex/allowed_domains.txt`。
# 4. 调用容器内的 `init_firewall.sh`，用 iptables/ipset 收紧网络。
# 5. 在容器内执行 `codex --sandbox workspace-write --ask-for-approval on-request ...`。
#
# 它不是 npm 发布脚本，也不是 Codex Agent Loop；它是一个容器化 sandbox
# launcher，用来模拟“文件系统可写、网络受控”的 Codex 执行环境。
#
# Usage:
#   ./run_in_container.sh [--work_dir directory] "COMMAND"
#
#   Examples:
#     ./run_in_container.sh --work_dir project/code "ls -la"
#     ./run_in_container.sh "echo Hello, world!"

# Default the work directory to WORKSPACE_ROOT_DIR if not provided.
# WORKSPACE_ROOT_DIR 是上层环境传入的项目根；没有传就使用当前目录。
WORK_DIR="${WORKSPACE_ROOT_DIR:-$(pwd)}"
# Default allowed domains - can be overridden with OPENAI_ALLOWED_DOMAINS env var
# 默认只允许访问 OpenAI API；多个域名用空格分隔。
OPENAI_ALLOWED_DOMAINS="${OPENAI_ALLOWED_DOMAINS:-api.openai.com}"

# Parse optional flag.
if [ "$1" = "--work_dir" ]; then
  if [ -z "$2" ]; then
    echo "Error: --work_dir flag provided but no directory specified."
    exit 1
  fi
  WORK_DIR="$2"
  shift 2
fi

WORK_DIR=$(realpath "$WORK_DIR")

# Generate a unique container name based on the normalized work directory
# 同一个 workdir 对应同一个容器名，方便启动前先清掉旧容器。
CONTAINER_NAME="codex_$(echo "$WORK_DIR" | sed 's/\//_/g' | sed 's/[^a-zA-Z0-9_-]//g')"

# Define cleanup to remove the container on script exit, ensuring no leftover containers
cleanup() {
  docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
}
# Trap EXIT to invoke cleanup regardless of how the script terminates
trap cleanup EXIT

# Ensure a command is provided.
if [ "$#" -eq 0 ]; then
  echo "Usage: $0 [--work_dir directory] \"COMMAND\""
  exit 1
fi

# Check if WORK_DIR is set.
if [ -z "$WORK_DIR" ]; then
  echo "Error: No work directory provided and WORKSPACE_ROOT_DIR is not set."
  exit 1
fi

# Verify that OPENAI_ALLOWED_DOMAINS is not empty
if [ -z "$OPENAI_ALLOWED_DOMAINS" ]; then
  echo "Error: OPENAI_ALLOWED_DOMAINS is empty."
  exit 1
fi

# Kill any existing container for the working directory using cleanup(), centralizing removal logic.
cleanup

# Run the container with the specified directory mounted at the same path inside the container.
# 这里需要 NET_ADMIN / NET_RAW，是因为后面要在容器内配置 iptables/ipset。
# 挂载路径使用 `/app$WORK_DIR`，这样容器内仍能保留原始绝对路径信息。
docker run --name "$CONTAINER_NAME" -d \
  -e OPENAI_API_KEY \
  --cap-add=NET_ADMIN \
  --cap-add=NET_RAW \
  -v "$WORK_DIR:/app$WORK_DIR" \
  codex \
  sleep infinity

# Write the allowed domains to a file in the container
# `init_firewall.sh` 从这个文件读取网络白名单。
docker exec --user root "$CONTAINER_NAME" bash -c "mkdir -p /etc/codex"
for domain in $OPENAI_ALLOWED_DOMAINS; do
  # Validate domain format to prevent injection
  if [[ ! "$domain" =~ ^[a-zA-Z0-9][a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$ ]]; then
    echo "Error: Invalid domain format: $domain"
    exit 1
  fi
  echo "$domain" | docker exec --user root -i "$CONTAINER_NAME" bash -c "cat >> /etc/codex/allowed_domains.txt"
done

# Set proper permissions on the domains file
docker exec --user root "$CONTAINER_NAME" bash -c "chmod 444 /etc/codex/allowed_domains.txt && chown root:root /etc/codex/allowed_domains.txt"

# Initialize the firewall inside the container as root user
# 初始化后，容器默认不能访问白名单之外的外网。
docker exec --user root "$CONTAINER_NAME" bash -c "/usr/local/bin/init_firewall.sh"

# Remove the firewall script after running it
docker exec --user root "$CONTAINER_NAME" bash -c "rm -f /usr/local/bin/init_firewall.sh"

# Execute the provided command in the container, ensuring it runs in the work directory.
# We use a parameterized bash command to safely handle the command and directory.

quoted_args=""
for arg in "$@"; do
  quoted_args+=" $(printf '%q' "$arg")"
done
# 参数经过 shell quote 后拼进容器内 bash 命令，避免空格和特殊字符被错误拆分。
docker exec -it "$CONTAINER_NAME" bash -c "cd \"/app$WORK_DIR\" && codex --sandbox workspace-write --ask-for-approval on-request ${quoted_args}"
