#!/bin/bash
set -euo pipefail  # Exit on error, undefined vars, and pipeline failures
IFS=$'\n\t'       # Stricter word splitting

# 这个脚本在 Codex Docker 容器内部以 root 身份执行。
#
# 目标：把容器网络从“默认可访问外网”改成“默认阻断，只允许访问指定域名”。
#
# 核心流程：
#
#   /etc/codex/allowed_domains.txt
#       |
#       v
#   dig resolve domains to A records
#       |
#       v
#   ipset allowed-domains
#       |
#       v
#   iptables OUTPUT allow only allowed-domains
#
# 注意：这是容器级网络控制，不是 Codex Agent Loop 里的 approval/sandbox 逻辑。

# Read allowed domains from file
# `run_in_container.sh` 会在启动容器后写入这个文件。
ALLOWED_DOMAINS_FILE="/etc/codex/allowed_domains.txt"
if [ -f "$ALLOWED_DOMAINS_FILE" ]; then
    ALLOWED_DOMAINS=()
    while IFS= read -r domain; do
        ALLOWED_DOMAINS+=("$domain")
    done < "$ALLOWED_DOMAINS_FILE"
    echo "Using domains from file: ${ALLOWED_DOMAINS[*]}"
else
    # Fallback to default domains
    ALLOWED_DOMAINS=("api.openai.com")
    echo "Domains file not found, using default: ${ALLOWED_DOMAINS[*]}"
fi

# Ensure we have at least one domain
if [ ${#ALLOWED_DOMAINS[@]} -eq 0 ]; then
    echo "ERROR: No allowed domains specified"
    exit 1
fi

# Flush existing rules and delete existing ipsets
# 先清空旧规则，保证重复初始化时不会叠加过期配置。
iptables -F
iptables -X
iptables -t nat -F
iptables -t nat -X
iptables -t mangle -F
iptables -t mangle -X
ipset destroy allowed-domains 2>/dev/null || true

# First allow DNS and localhost before any restrictions
# DNS 必须先放行，否则后面无法把允许域名解析成 IP。
# Allow outbound DNS
iptables -A OUTPUT -p udp --dport 53 -j ACCEPT
# Allow inbound DNS responses
iptables -A INPUT -p udp --sport 53 -j ACCEPT
# Allow localhost
iptables -A INPUT -i lo -j ACCEPT
iptables -A OUTPUT -o lo -j ACCEPT

# Create ipset with CIDR support
# ipset 用来保存允许访问的目标 IP，iptables 可以高效引用这个集合。
ipset create allowed-domains hash:net

# Resolve and add other allowed domains
# 这里把域名解析成当前 A 记录并加入 ipset。它不是动态 DNS 监听，
# 如果域名 IP 后续变化，需要重新运行脚本刷新规则。
for domain in "${ALLOWED_DOMAINS[@]}"; do
    echo "Resolving $domain..."
    ips=$(dig +short A "$domain")
    if [ -z "$ips" ]; then
        echo "ERROR: Failed to resolve $domain"
        exit 1
    fi

    while read -r ip; do
        if [[ ! "$ip" =~ ^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$ ]]; then
            echo "ERROR: Invalid IP from DNS for $domain: $ip"
            exit 1
        fi
        echo "Adding $ip for $domain"
        ipset add allowed-domains "$ip"
    done < <(echo "$ips")
done

# Get host IP from default route
# Docker 容器仍需要访问宿主机所在网段，例如挂载、代理或内部通信场景。
HOST_IP=$(ip route | grep default | cut -d" " -f3)
if [ -z "$HOST_IP" ]; then
    echo "ERROR: Failed to detect host IP"
    exit 1
fi

HOST_NETWORK=$(echo "$HOST_IP" | sed "s/\.[0-9]*$/.0\/24/")
echo "Host network detected as: $HOST_NETWORK"

# Set up remaining iptables rules
# 放行宿主机网段，避免网络收口后容器和 Docker host 之间的必要通信被切断。
iptables -A INPUT -s "$HOST_NETWORK" -j ACCEPT
iptables -A OUTPUT -d "$HOST_NETWORK" -j ACCEPT

# Set default policies to DROP first
# 默认策略设为 DROP，这是网络收口的关键：除显式允许外全部拒绝。
iptables -P INPUT DROP
iptables -P FORWARD DROP
iptables -P OUTPUT DROP

# First allow established connections for already approved traffic
# 已建立连接的返回流量必须允许，否则即使 OUTPUT 放行，请求响应也回不来。
iptables -A INPUT -m state --state ESTABLISHED,RELATED -j ACCEPT
iptables -A OUTPUT -m state --state ESTABLISHED,RELATED -j ACCEPT

# Then allow only specific outbound traffic to allowed domains
# 只允许访问刚才解析进 ipset 的白名单 IP。
iptables -A OUTPUT -m set --match-set allowed-domains dst -j ACCEPT

# Append final REJECT rules for immediate error responses
# For TCP traffic, send a TCP reset; for UDP, send ICMP port unreachable.
# 末尾用 REJECT 而不是静默 DROP，让失败快速返回，避免 Codex 工具调用长时间挂起。
iptables -A INPUT -p tcp -j REJECT --reject-with tcp-reset
iptables -A INPUT -p udp -j REJECT --reject-with icmp-port-unreachable
iptables -A OUTPUT -p tcp -j REJECT --reject-with tcp-reset
iptables -A OUTPUT -p udp -j REJECT --reject-with icmp-port-unreachable
iptables -A FORWARD -p tcp -j REJECT --reject-with tcp-reset
iptables -A FORWARD -p udp -j REJECT --reject-with icmp-port-unreachable

echo "Firewall configuration complete"
echo "Verifying firewall rules..."
# 负向验证：example.com 不在默认白名单内，应该无法访问。
if curl --connect-timeout 5 https://example.com >/dev/null 2>&1; then
    echo "ERROR: Firewall verification failed - was able to reach https://example.com"
    exit 1
else
    echo "Firewall verification passed - unable to reach https://example.com as expected"
fi

# Always verify OpenAI API access is working
# 正向验证：脚本当前固定要求 api.openai.com 仍可访问。
if ! curl --connect-timeout 5 https://api.openai.com >/dev/null 2>&1; then
    echo "ERROR: Firewall verification failed - unable to reach https://api.openai.com"
    exit 1
else
    echo "Firewall verification passed - able to reach https://api.openai.com as expected"
fi
