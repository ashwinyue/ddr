#!/bin/bash
# scripts/setup-weixin.sh — 微信机器人交互式扫码配置脚本
#
# Usage:
#   ./scripts/setup-weixin.sh            # 交互式，默认写入 .env
#   ./scripts/setup-weixin.sh --config   # 同时写入 config.yaml channels.weixin

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

source "$SCRIPT_DIR/lib/weixin_auth.sh"

# ── 颜色 ──────────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BOLD='\033[1m'; CYAN='\033[0;36m'; NC='\033[0m'
info()  { echo -e "${GREEN}✅ $*${NC}"; }
warn()  { echo -e "${YELLOW}⚠️  $*${NC}"; }
error() { echo -e "${RED}❌ $*${NC}" >&2; }
step()  { echo -e "\n${BOLD}── $*${NC}"; }

# ── 参数解析 ──────────────────────────────────────────────────────────────────
WRITE_CONFIG=false

for arg in "$@"; do
    case "$arg" in
        --config) WRITE_CONFIG=true ;;
        --help|-h)
            echo "Usage: $0 [--config]"
            echo "  --config  同时更新 config.yaml channels.weixin 节"
            exit 0 ;;
    esac
done

# ── 欢迎界面 ──────────────────────────────────────────────────────────────────
clear
echo ""
echo -e "${BOLD}╔══════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║   DeerFlow × 微信机器人扫码配置         ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════╝${NC}"
echo ""
echo -e "   配置: ${CYAN}$([ "$WRITE_CONFIG" = true ] && echo '.env + config.yaml' || echo '.env')${NC}"
echo ""

# ── 前置检查 ──────────────────────────────────────────────────────────────────
step "环境检查"

if ! command -v curl &>/dev/null; then
    error "未找到 curl，请先安装 curl"
    exit 1
fi
info "curl 可用"

# .env 文件
ENV_FILE="$PROJECT_ROOT/.env"
if [[ ! -f "$ENV_FILE" ]]; then
    if [[ -f "$PROJECT_ROOT/.env.example" ]]; then
        cp "$PROJECT_ROOT/.env.example" "$ENV_FILE"
        info "已从 .env.example 创建 .env"
    else
        touch "$ENV_FILE"
        warn ".env 不存在，已创建空文件"
    fi
fi

# config.yaml
CONFIG_FILE="$PROJECT_ROOT/config.yaml"
if [[ "$WRITE_CONFIG" = true && ! -f "$CONFIG_FILE" ]]; then
    if [[ -f "$PROJECT_ROOT/config.example.yaml" ]]; then
        cp "$PROJECT_ROOT/config.example.yaml" "$CONFIG_FILE"
        info "已从 config.example.yaml 创建 config.yaml"
    else
        error "config.yaml 不存在，请先运行 make config"
        exit 1
    fi
fi

# ── 微信扫码认证 ──────────────────────────────────────────────────────────────
step "微信扫码授权"

if ! weixin_auth_interactive; then
    error "扫码认证失败"
    exit 1
fi

BOT_TOKEN="$WEIXIN_AUTH_BOT_TOKEN"
BOT_ID="$WEIXIN_AUTH_BOT_ID"
BASE_URL="$WEIXIN_AUTH_BASE_URL"

echo ""
echo -e "${BOLD}   获取到凭证：${NC}"
echo "   Bot ID    : $BOT_ID"
echo "   Bot Token : ${BOT_TOKEN:0:6}$(printf '*%.0s' {1..20})${BOT_TOKEN: -4}"
echo "   Base URL  : $BASE_URL"

# ── 写入 .env ─────────────────────────────────────────────────────────────────
step "写入 .env"

_upsert_env() {
    local file="$1" key="$2" value="$3"
    if grep -qE "^#?[[:space:]]*${key}=" "$file" 2>/dev/null; then
        sed -i.bak -E "s|^#?[[:space:]]*${key}=.*|${key}=${value}|" "$file"
        rm -f "${file}.bak"
    else
        echo "${key}=${value}" >> "$file"
    fi
}

_upsert_env "$ENV_FILE" "WEIXIN_BOT_TOKEN" "$BOT_TOKEN"
_upsert_env "$ENV_FILE" "WEIXIN_BOT_ID"    "$BOT_ID"
_upsert_env "$ENV_FILE" "WEIXIN_BASE_URL"  "$BASE_URL"

info ".env 已更新"

# ── 写入 config.yaml（可选）─────────────────────────────────────────────────
if [[ "$WRITE_CONFIG" = true ]]; then
    step "更新 config.yaml"

    python3 - <<PYEOF
import re, sys

config_path = '${CONFIG_FILE}'
bot_token   = '${BOT_TOKEN}'
bot_id      = '${BOT_ID}'
base_url    = '${BASE_URL}'

with open(config_path, 'r') as f:
    content = f.read()

weixin_block = f"""  weixin:
    enabled: true
    bot_token: {bot_token}
    bot_id: {bot_id}
    base_url: {base_url}"""

# 已存在 weixin: 节 → 整块替换
if re.search(r'weixin:', content):
    content = re.sub(
        r'(#+\s*)?weixin:.*?(?=\n\s*\w|\Z)',
        weixin_block,
        content,
        count=1,
        flags=re.DOTALL,
    )
else:
    # 在 channels: 节末尾追加
    channels_end = re.search(r'^channels:', content, re.MULTILINE)
    if channels_end:
        rest = content[channels_end.start():]
        next_top = re.search(r'\n\S', rest[1:])
        if next_top:
            insert_pos = channels_end.start() + 1 + next_top.start()
            content = content[:insert_pos] + '\n' + weixin_block + '\n' + content[insert_pos:]
        else:
            content = content.rstrip('\n') + '\n' + weixin_block + '\n'
    else:
        content = content.rstrip('\n') + '\nchannels:\n' + weixin_block + '\n'

with open(config_path, 'w') as f:
    f.write(content)

print('  config.yaml 已更新')
PYEOF

    info "config.yaml channels.weixin 已启用"
fi

# ── 完成 ──────────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}╔══════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║   ✅ 微信配置完成！                      ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════╝${NC}"
echo ""
echo "   Bot ID  : $BOT_ID"
echo ""
echo -e "${YELLOW}下一步：${NC}"
echo "  1. 在 config.yaml 中确认 channels.weixin.enabled: true"
echo "  2. 启动服务: make dev"
echo ""
echo -e "${CYAN}提示：${NC}在微信中向机器人发送任意消息测试连通性"
echo ""
