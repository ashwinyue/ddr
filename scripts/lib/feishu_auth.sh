#!/bin/bash
# scripts/lib/feishu_auth.sh — 飞书 OAuth 设备流认证库
#
# Usage:
#   source ./scripts/lib/feishu_auth.sh
#   feishu_auth_interactive ["feishu"|"lark"]
#   # Sets: FEISHU_AUTH_APP_ID, FEISHU_AUTH_APP_SECRET, FEISHU_AUTH_DOMAIN

# ── 常量 ──────────────────────────────────────────────────────────────────────
readonly FEISHU_ACCOUNTS_URL="https://accounts.feishu.cn"
readonly LARK_ACCOUNTS_URL="https://accounts.larksuite.com"
readonly FEISHU_OPEN_API="https://open.feishu.cn"
readonly LARK_OPEN_API="https://open.larksuite.com"

# ── 颜色输出（不与主脚本变量冲突）────────────────────────────────────────────
if command -v tput &>/dev/null && tput colors &>/dev/null 2>&1; then
    _fa_red()    { echo -e "$(tput setaf 1)$*$(tput sgr0)"; }
    _fa_green()  { echo -e "$(tput setaf 2)$*$(tput sgr0)"; }
    _fa_yellow() { echo -e "$(tput setaf 3)$*$(tput sgr0)"; }
    _fa_cyan()   { echo -e "$(tput setaf 6)$*$(tput sgr0)"; }
    _fa_bold()   { echo -e "$(tput bold)$*$(tput sgr0)"; }
else
    _fa_red()    { echo "$*"; }
    _fa_green()  { echo "$*"; }
    _fa_yellow() { echo "$*"; }
    _fa_cyan()   { echo "$*"; }
    _fa_bold()   { echo "$*"; }
fi

# ── 内部工具 ──────────────────────────────────────────────────────────────────

_fa_json_str() {
    local json="$1" key="$2"
    echo "$json" | grep -o "\"$key\":\"[^\"]*\"" 2>/dev/null \
        | head -1 | sed 's/.*":"\(.*\)"/\1/' | sed 's/\\"/"/g'
}

_fa_json_num() {
    local json="$1" key="$2"
    echo "$json" | grep -o "\"$key\":[0-9]*" 2>/dev/null | head -1 | cut -d':' -f2
}

_fa_install_qrencode() {
    _fa_cyan "   未检测到 qrencode，尝试自动安装..."
    if [[ "$OSTYPE" == "darwin"* ]]; then
        command -v brew &>/dev/null && brew install qrencode &>/dev/null || return 1
    elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
        if   command -v apt-get &>/dev/null; then sudo apt-get install -y qrencode &>/dev/null
        elif command -v yum     &>/dev/null; then sudo yum     install -y qrencode &>/dev/null
        elif command -v dnf     &>/dev/null; then sudo dnf     install -y qrencode &>/dev/null
        elif command -v pacman  &>/dev/null; then sudo pacman  -S --noconfirm qrencode &>/dev/null
        else return 1
        fi
    else
        return 1
    fi
    command -v qrencode &>/dev/null
}

# 在终端打印二维码；失败返回 1（调用方回退到显示链接）
_fa_print_qr() {
    local text="$1"
    if ! command -v qrencode &>/dev/null; then
        _fa_install_qrencode || return 1
    fi
    echo ""
    qrencode -t ANSIUTF8 "$text" 2>/dev/null || qrencode -t ANSI "$text" || return 1
    echo ""
}

# ── OAuth API ─────────────────────────────────────────────────────────────────

_fa_oauth_init() {
    curl -s -X POST "${1}/oauth/v1/app/registration" \
        -H "Content-Type: application/x-www-form-urlencoded" \
        -d "action=init" --max-time 10 2>/dev/null || echo '{"error":"network"}'
}

_fa_oauth_begin() {
    curl -s -X POST "${1}/oauth/v1/app/registration" \
        -H "Content-Type: application/x-www-form-urlencoded" \
        -d "action=begin" \
        -d "archetype=PersonalAgent" \
        -d "auth_method=client_secret" \
        -d "request_user_info=open_id" \
        --max-time 10 2>/dev/null || echo '{"error":"network"}'
}

_fa_oauth_poll() {
    curl -s -X POST "${1}/oauth/v1/app/registration" \
        -H "Content-Type: application/x-www-form-urlencoded" \
        -d "action=poll" \
        -d "device_code=${2}" \
        --max-time 10 2>/dev/null || echo '{"error":"network"}'
}

# ── 公开 API ──────────────────────────────────────────────────────────────────

# 验证凭证有效性
# Usage: feishu_validate_credentials <app_id> <app_secret> [feishu|lark]
# Returns: 0=valid, 1=invalid
feishu_validate_credentials() {
    local app_id="${1:-}" app_secret="${2:-}" domain="${3:-feishu}"
    local base_url="$FEISHU_OPEN_API"
    [[ "$domain" == "lark" ]] && base_url="$LARK_OPEN_API"

    app_id=$(echo "$app_id" | tr -d '[:space:]')
    app_secret=$(echo "$app_secret" | tr -d '[:space:]')
    [[ -z "$app_id" || -z "$app_secret" ]] && return 1

    local resp
    resp=$(curl -s -X POST "${base_url}/open-apis/auth/v3/tenant_access_token/internal" \
        -H "Content-Type: application/json" \
        -d "{\"app_id\":\"${app_id}\",\"app_secret\":\"${app_secret}\"}" \
        --max-time 10 2>/dev/null)
    [[ -n "$resp" ]] && echo "$resp" | grep -q '"code":0'
}

# 交互式扫码认证（阻塞，直到成功/失败/超时）
# Usage: feishu_auth_interactive ["feishu"|"lark"]
# Sets:  FEISHU_AUTH_APP_ID, FEISHU_AUTH_APP_SECRET, FEISHU_AUTH_DOMAIN
# Returns: 0=success, 1=failure
feishu_auth_interactive() {
    local domain="${1:-feishu}"
    local accounts_url="$FEISHU_ACCOUNTS_URL"
    [[ "$domain" == "lark" ]] && accounts_url="$LARK_ACCOUNTS_URL"

    # 步骤 1: 初始化
    _fa_cyan "   检查认证方式支持..."
    local init_resp
    init_resp=$(_fa_oauth_init "$accounts_url")
    if echo "$init_resp" | grep -q '"error"' || ! echo "$init_resp" | grep -q "client_secret"; then
        _fa_red "   ❌ 无法连接飞书服务器或不支持 client_secret 认证"
        return 1
    fi

    # 步骤 2: 获取 device_code 与扫码链接
    local begin_resp
    begin_resp=$(_fa_oauth_begin "$accounts_url")
    if echo "$begin_resp" | grep -q '"error"'; then
        _fa_red "   ❌ 启动认证流程失败"
        return 1
    fi

    local device_code verification_uri interval expire_in
    device_code=$(_fa_json_str "$begin_resp" "device_code")
    verification_uri=$(_fa_json_str "$begin_resp" "verification_uri_complete")
    interval=$(_fa_json_num "$begin_resp" "interval")
    expire_in=$(_fa_json_num "$begin_resp" "expire_in")

    [[ -z "$interval"   ]] && interval=5
    [[ -z "$expire_in"  ]] && expire_in=600
    [[ -z "$device_code" || -z "$verification_uri" ]] && { _fa_red "   ❌ 获取认证信息失败"; return 1; }

    # 步骤 3: 显示二维码
    echo ""
    _fa_bold "   请用飞书 App 扫码，完成机器人授权："
    if ! _fa_print_qr "$verification_uri"; then
        _fa_yellow "   未能生成终端二维码，请在浏览器打开以下链接扫码："
        _fa_cyan   "   $verification_uri"
        echo ""
    fi

    # 步骤 4: 轮询
    local start_time current_time elapsed remaining
    local spinner="⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
    local si=0
    start_time=$(date +%s)

    _fa_cyan "   等待扫码完成，超时: ${expire_in}s ..."

    while true; do
        current_time=$(date +%s)
        elapsed=$(( current_time - start_time ))

        if [[ $elapsed -ge $expire_in ]]; then
            echo ""
            _fa_yellow "   ⚠️  扫码超时，请重新运行脚本"
            return 1
        fi

        remaining=$(( expire_in - elapsed ))
        printf "\r   %s 等待扫码... (%ds 剩余)" "${spinner:$si:1}" "$remaining"
        si=$(( (si + 1) % 10 ))

        local poll_resp
        poll_resp=$(_fa_oauth_poll "$accounts_url" "$device_code")

        if echo "$poll_resp" | grep -q '"client_id"' && echo "$poll_resp" | grep -q '"client_secret"'; then
            echo ""
            echo ""
            local app_id app_secret
            app_id=$(_fa_json_str "$poll_resp" "client_id")
            app_secret=$(_fa_json_str "$poll_resp" "client_secret")

            _fa_cyan "   验证凭证有效性..."
            if feishu_validate_credentials "$app_id" "$app_secret" "$domain"; then
                _fa_green "   ✅ 扫码授权成功！"
                FEISHU_AUTH_APP_ID="$app_id"
                FEISHU_AUTH_APP_SECRET="$app_secret"
                FEISHU_AUTH_DOMAIN="$domain"
                return 0
            else
                _fa_red "   ❌ 凭证验证失败，授权可能已被撤销"
                return 1
            fi
        fi

        if echo "$poll_resp" | grep -q '"error"'; then
            local err_code
            err_code=$(_fa_json_str "$poll_resp" "error")
            case "$err_code" in
                authorization_pending) ;;
                slow_down)    interval=$(( interval + 5 )) ;;
                access_denied)
                    echo ""; _fa_red "   ❌ 用户拒绝授权"; return 1 ;;
                expired_token)
                    echo ""; _fa_red "   ❌ 会话已过期，请重新运行"; return 1 ;;
                network)
                    echo ""; _fa_red "   ❌ 网络请求失败"; return 1 ;;
                *)
                    echo ""; _fa_red "   ❌ 未知错误: $err_code"; return 1 ;;
            esac
        fi

        sleep "$interval"
    done
}

# 导出状态变量
export FEISHU_AUTH_APP_ID=""
export FEISHU_AUTH_APP_SECRET=""
export FEISHU_AUTH_DOMAIN=""
