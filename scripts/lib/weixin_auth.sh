#!/bin/bash
# scripts/lib/weixin_auth.sh — 微信 ilink 扫码认证库
#
# Usage:
#   source ./scripts/lib/weixin_auth.sh
#   weixin_auth_interactive
#   # Sets: WEIXIN_AUTH_BOT_TOKEN, WEIXIN_AUTH_BOT_ID, WEIXIN_AUTH_BASE_URL

readonly WEIXIN_ILINK_BASE="https://ilinkai.weixin.qq.com"
readonly WEIXIN_BOT_TYPE="3"
readonly WEIXIN_POLL_TIMEOUT=38   # 长轮询服务端最长 35s，客户端留 3s 余量
readonly WEIXIN_QR_MAX_REFRESH=3
readonly WEIXIN_LOGIN_TIMEOUT=480  # 总超时 8 分钟

# ── 颜色（不与主脚本冲突）────────────────────────────────────────────────────
if command -v tput &>/dev/null && tput colors &>/dev/null 2>&1; then
    _wx_red()    { echo -e "$(tput setaf 1)$*$(tput sgr0)"; }
    _wx_green()  { echo -e "$(tput setaf 2)$*$(tput sgr0)"; }
    _wx_yellow() { echo -e "$(tput setaf 3)$*$(tput sgr0)"; }
    _wx_cyan()   { echo -e "$(tput setaf 6)$*$(tput sgr0)"; }
    _wx_bold()   { echo -e "$(tput bold)$*$(tput sgr0)"; }
else
    _wx_red()    { echo "$*"; }
    _wx_green()  { echo "$*"; }
    _wx_yellow() { echo "$*"; }
    _wx_cyan()   { echo "$*"; }
    _wx_bold()   { echo "$*"; }
fi

# ── JSON 工具（纯 bash，无 jq 依赖）─────────────────────────────────────────
_wx_json_str() {
    local json="$1" key="$2"
    echo "$json" | grep -o "\"$key\":\"[^\"]*\"" 2>/dev/null \
        | head -1 | sed 's/.*":"\(.*\)"/\1/'
}

# ── qrencode 安装 ─────────────────────────────────────────────────────────────
_wx_install_qrencode() {
    _wx_cyan "   未检测到 qrencode，尝试安装..."
    if [[ "$OSTYPE" == "darwin"* ]]; then
        command -v brew &>/dev/null && brew install qrencode &>/dev/null || return 1
    elif command -v apt-get &>/dev/null; then
        apt-get install -y qrencode &>/dev/null
    elif command -v yum &>/dev/null; then
        yum install -y qrencode &>/dev/null
    else
        return 1
    fi
    command -v qrencode &>/dev/null
}

_wx_print_qr() {
    local text="$1"
    if ! command -v qrencode &>/dev/null; then
        _wx_install_qrencode || return 1
    fi
    echo ""
    qrencode -t ANSIUTF8 "$text" 2>/dev/null || qrencode -t ANSI "$text" || return 1
    echo ""
}

# ── ilink API ─────────────────────────────────────────────────────────────────

# 获取二维码（GET，无 token）
_wx_get_qrcode() {
    curl -s --max-time 10 \
        "${WEIXIN_ILINK_BASE}/ilink/bot/get_bot_qrcode?bot_type=${WEIXIN_BOT_TYPE}" \
        2>/dev/null || echo '{"error":"network"}'
}

# 轮询扫码状态（长轮询，服务端最长持有 35s）
_wx_poll_status() {
    local qrcode="$1"
    curl -s --max-time "${WEIXIN_POLL_TIMEOUT}" \
        -H "iLink-App-ClientVersion: 1" \
        "${WEIXIN_ILINK_BASE}/ilink/bot/get_qrcode_status?qrcode=${qrcode}" \
        2>/dev/null || echo '{"status":"wait"}'
}

# ── 公开 API ──────────────────────────────────────────────────────────────────

# 交互式微信扫码认证（阻塞，直到成功/超时）
# Sets: WEIXIN_AUTH_BOT_TOKEN, WEIXIN_AUTH_BOT_ID, WEIXIN_AUTH_BASE_URL
# Returns: 0=success, 1=failure
weixin_auth_interactive() {
    # 1. 获取二维码
    _wx_cyan "   正在获取微信二维码..."
    local qr_resp qrcode qrcode_url
    qr_resp=$(_wx_get_qrcode)
    qrcode=$(_wx_json_str "$qr_resp" "qrcode")
    qrcode_url=$(_wx_json_str "$qr_resp" "qrcode_img_content")

    if [[ -z "$qrcode" || -z "$qrcode_url" ]]; then
        _wx_red "   ❌ 获取二维码失败：$qr_resp"
        return 1
    fi

    _wx_bold "   请用微信扫码，完成机器人授权："
    if ! _wx_print_qr "$qrcode_url"; then
        _wx_yellow "   未能生成终端二维码，请在浏览器打开："
        _wx_cyan   "   $qrcode_url"
        echo ""
    fi

    # 2. 轮询等待扫码
    local start_time elapsed refresh_count=0 scanned=false
    local spinner="⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏" si=0
    start_time=$(date +%s)

    _wx_cyan "   等待扫码确认，超时 ${WEIXIN_LOGIN_TIMEOUT}s ..."

    while true; do
        elapsed=$(( $(date +%s) - start_time ))
        if [[ $elapsed -ge $WEIXIN_LOGIN_TIMEOUT ]]; then
            echo ""
            _wx_yellow "   ⚠️  登录超时，请重新运行脚本"
            return 1
        fi

        printf "\r   %s 等待中... (%ds)" "${spinner:$si:1}" "$(( WEIXIN_LOGIN_TIMEOUT - elapsed ))"
        si=$(( (si + 1) % 10 ))

        local poll_resp status
        poll_resp=$(_wx_poll_status "$qrcode")
        status=$(_wx_json_str "$poll_resp" "status")

        case "$status" in
            wait)
                # 正常等待，继续
                ;;
            scaned)
                if [[ "$scanned" == false ]]; then
                    echo ""
                    _wx_cyan "   👀 已扫码，请在微信中确认..."
                    scanned=true
                fi
                ;;
            confirmed)
                echo ""
                local bot_token bot_id base_url
                bot_token=$(_wx_json_str "$poll_resp" "bot_token")
                bot_id=$(_wx_json_str "$poll_resp" "ilink_bot_id")
                base_url=$(_wx_json_str "$poll_resp" "baseurl")

                if [[ -z "$bot_id" ]]; then
                    _wx_red "   ❌ 登录失败：服务端未返回 ilink_bot_id"
                    return 1
                fi

                _wx_green "   ✅ 微信扫码授权成功！"
                WEIXIN_AUTH_BOT_TOKEN="$bot_token"
                WEIXIN_AUTH_BOT_ID="$bot_id"
                WEIXIN_AUTH_BASE_URL="${base_url:-$WEIXIN_ILINK_BASE}"
                return 0
                ;;
            expired)
                refresh_count=$(( refresh_count + 1 ))
                if [[ $refresh_count -gt $WEIXIN_QR_MAX_REFRESH ]]; then
                    echo ""
                    _wx_red "   ❌ 二维码多次过期，请重新运行"
                    return 1
                fi
                echo ""
                _wx_yellow "   ⏳ 二维码过期，正在刷新 (${refresh_count}/${WEIXIN_QR_MAX_REFRESH})..."
                qr_resp=$(_wx_get_qrcode)
                qrcode=$(_wx_json_str "$qr_resp" "qrcode")
                qrcode_url=$(_wx_json_str "$qr_resp" "qrcode_img_content")
                if [[ -z "$qrcode" ]]; then
                    _wx_red "   ❌ 刷新二维码失败"
                    return 1
                fi
                scanned=false
                _wx_bold "   请重新扫码："
                if ! _wx_print_qr "$qrcode_url"; then
                    _wx_cyan "   $qrcode_url"
                fi
                ;;
            *)
                # 长轮询超时（status 为空），正常继续
                ;;
        esac

        sleep 1
    done
}

# 导出状态变量
export WEIXIN_AUTH_BOT_TOKEN=""
export WEIXIN_AUTH_BOT_ID=""
export WEIXIN_AUTH_BASE_URL=""
