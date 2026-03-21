#!/bin/bash
# scripts/setup-feishu.sh — 飞书机器人交互式扫码配置脚本
#
# Usage:
#   ./scripts/setup-feishu.sh            # 交互式，默认写入 .env
#   ./scripts/setup-feishu.sh --lark     # Lark 国际版
#   ./scripts/setup-feishu.sh --config   # 同时写入 config.yaml channels.feishu

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

source "$SCRIPT_DIR/lib/feishu_auth.sh"

# ── 颜色 ──────────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BOLD='\033[1m'; CYAN='\033[0;36m'; NC='\033[0m'
info()  { echo -e "${GREEN}✅ $*${NC}"; }
warn()  { echo -e "${YELLOW}⚠️  $*${NC}"; }
error() { echo -e "${RED}❌ $*${NC}" >&2; }
step()  { echo -e "\n${BOLD}── $*${NC}"; }

# ── 参数解析 ──────────────────────────────────────────────────────────────────
DOMAIN="feishu"
WRITE_CONFIG=false

for arg in "$@"; do
    case "$arg" in
        --lark)   DOMAIN="lark" ;;
        --config) WRITE_CONFIG=true ;;
        --help|-h)
            echo "Usage: $0 [--lark] [--config]"
            echo "  --lark    使用 Lark 国际版 (larksuite.com)"
            echo "  --config  同时更新 config.yaml channels.feishu 节"
            exit 0 ;;
    esac
done

# ── 欢迎界面 ──────────────────────────────────────────────────────────────────
clear
echo ""
echo -e "${BOLD}╔══════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║   DeerFlow × 飞书机器人扫码配置         ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════╝${NC}"
echo ""
echo -e "   环境: ${CYAN}${DOMAIN}${NC}"
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

# ── 飞书扫码认证 ──────────────────────────────────────────────────────────────
step "飞书扫码授权"

if ! feishu_auth_interactive "$DOMAIN"; then
    error "扫码认证失败"
    exit 1
fi

APP_ID="$FEISHU_AUTH_APP_ID"
APP_SECRET="$FEISHU_AUTH_APP_SECRET"

echo ""
echo -e "${BOLD}   获取到凭证：${NC}"
echo "   App ID     : $APP_ID"
echo "   App Secret : ${APP_SECRET:0:6}$(printf '*%.0s' {1..20})${APP_SECRET: -4}"

# ── 写入 .env ─────────────────────────────────────────────────────────────────
step "写入 .env"

_upsert_env() {
    local file="$1" key="$2" value="$3"
    if grep -qE "^#?[[:space:]]*${key}=" "$file" 2>/dev/null; then
        # 替换（包括注释行），-E 兼容 macOS sed
        sed -i.bak -E "s|^#?[[:space:]]*${key}=.*|${key}=${value}|" "$file"
        rm -f "${file}.bak"
    else
        # 追加
        echo "${key}=${value}" >> "$file"
    fi
}

_upsert_env "$ENV_FILE" "FEISHU_APP_ID"     "$APP_ID"
_upsert_env "$ENV_FILE" "FEISHU_APP_SECRET" "$APP_SECRET"

info ".env 已更新"

# ── 写入 config.yaml（可选）─────────────────────────────────────────────────
if [[ "$WRITE_CONFIG" = true ]]; then
    step "更新 config.yaml"

    python3 - <<PYEOF
import re, sys

config_path = '${CONFIG_FILE}'
app_id      = '${APP_ID}'
app_secret  = '${APP_SECRET}'

with open(config_path, 'r') as f:
    content = f.read()

feishu_block = f"""  feishu:
    enabled: true
    app_id: {app_id}
    app_secret: {app_secret}"""

# 已存在 feishu: 节 → 整块替换
pattern = r'(#\s*)?feishu:\n(\s+[^\n]+\n)+'
if re.search(r'feishu:', content):
    content = re.sub(
        r'(#+\s*)?feishu:.*?(?=\n\s*\w|\Z)',
        feishu_block,
        content,
        count=1,
        flags=re.DOTALL,
    )
else:
    # 在 channels: 节末尾追加
    channels_end = re.search(r'^channels:', content, re.MULTILINE)
    if channels_end:
        # 找到 channels 块结束位置（下一个顶级 key 或 EOF）
        rest = content[channels_end.start():]
        next_top = re.search(r'\n\S', rest[1:])
        if next_top:
            insert_pos = channels_end.start() + 1 + next_top.start()
            content = content[:insert_pos] + '\n' + feishu_block + '\n' + content[insert_pos:]
        else:
            content = content.rstrip('\n') + '\n' + feishu_block + '\n'
    else:
        content = content.rstrip('\n') + '\nchannels:\n' + feishu_block + '\n'

with open(config_path, 'w') as f:
    f.write(content)

print('  config.yaml 已更新')
PYEOF

    info "config.yaml channels.feishu 已启用"
fi

# ── 完成 ──────────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}╔══════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║   ✅ 飞书配置完成！                      ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════╝${NC}"
echo ""
echo "   App ID   : $APP_ID"
echo "   Domain   : $DOMAIN"
echo ""
echo -e "${YELLOW}下一步：${NC}"
echo "  1. 在飞书开放平台开启「接收消息」事件订阅（长连接模式）"
echo "  2. 确保已安装 lark-oapi: cd backend && uv add lark-oapi"
echo "  3. 启动服务: make dev"
echo ""
echo -e "${CYAN}提示：${NC}首次使用可在飞书机器人对话中发送任意消息测试连通性"
echo ""
