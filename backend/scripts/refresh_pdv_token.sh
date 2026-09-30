#!/bin/bash
# =============================================================================
# PDV Token Refresh Script
# =============================================================================
# Refreshes the YourPDVService auth token for PDV API access.
# 
# Usage:
#   ./refresh_pdv_token.sh              # Interactive (opens browser)
#   ./refresh_pdv_token.sh --check      # Check token status only
#   ./refresh_pdv_token.sh --cron       # For cron job (logs to file)
#
# Setup cron for daily refresh (runs at 6am):
#   0 6 * * * /path/to/refresh_pdv_token.sh --cron >> /var/log/pdv_token.log 2>&1
# =============================================================================

set -e

# Configuration
TOKEN_FILE="${HOME}/.config/your-pdv-service/auth_token"
PDV_AUTH_BIN="${HOME}/.local/bin/your-pdv-serviceauth"
LOG_FILE="/var/log/pdv_token.log"

# Detect platform
PLATFORM=$(uname -s | tr '[:upper:]' '[:lower:]')
ARCH=$(uname -m)

if [[ "$PLATFORM" == "darwin" ]]; then
    BINARY_NAME="your-pdv-serviceauth-darwin-amd64"
elif [[ "$ARCH" == "aarch64" || "$ARCH" == "arm64" ]]; then
    BINARY_NAME="your-pdv-serviceauth-linux-arm64"
else
    BINARY_NAME="your-pdv-serviceauth-linux-amd64"
fi

DOWNLOAD_URL="https://artifactory-rd.example.com/artifactory/list/your-company-generic/qe/your-pdv-service-auth-tool/${BINARY_NAME}-latest.tar.gz"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log() {
    echo -e "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

log_success() {
    log "${GREEN}✓ $1${NC}"
}

log_warning() {
    log "${YELLOW}⚠ $1${NC}"
}

log_error() {
    log "${RED}✗ $1${NC}"
}

# Check token expiry
check_token() {
    if [[ ! -f "$TOKEN_FILE" ]]; then
        echo "NO_TOKEN"
        return
    fi

    TOKEN=$(cat "$TOKEN_FILE" | sed 's/^Bearer //')
    
    # Decode JWT and get expiry
    PAYLOAD=$(echo "$TOKEN" | cut -d'.' -f2 | base64 -d 2>/dev/null || echo "{}")
    EXP=$(echo "$PAYLOAD" | grep -o '"exp":[0-9]*' | cut -d':' -f2)
    
    if [[ -z "$EXP" ]]; then
        echo "INVALID"
        return
    fi

    NOW=$(date +%s)
    DIFF=$((EXP - NOW))
    
    if [[ $DIFF -lt 0 ]]; then
        echo "EXPIRED"
    elif [[ $DIFF -lt 3600 ]]; then
        echo "EXPIRING_SOON"  # Less than 1 hour
    else
        HOURS=$((DIFF / 3600))
        echo "VALID:${HOURS}h"
    fi
}

# Download your-pdv-serviceauth if not present
ensure_your-pdv-service_binary() {
    if [[ -x "$PDV_AUTH_BIN" ]]; then
        return 0
    fi

    log "Downloading your-pdv-serviceauth..."
    mkdir -p "$(dirname "$PDV_AUTH_BIN")"
    
    TEMP_DIR=$(mktemp -d)
    curl -sL "$DOWNLOAD_URL" | tar xzv -C "$TEMP_DIR"
    
    mv "$TEMP_DIR/dist/$BINARY_NAME" "$PDV_AUTH_BIN"
    chmod +x "$PDV_AUTH_BIN"
    
    # Remove quarantine on macOS
    if [[ "$PLATFORM" == "darwin" ]]; then
        xattr -d com.apple.quarantine "$PDV_AUTH_BIN" 2>/dev/null || true
    fi
    
    rm -rf "$TEMP_DIR"
    log_success "Downloaded your-pdv-serviceauth to $PDV_AUTH_BIN"
}

# Refresh token
refresh_token() {
    ensure_your-pdv-service_binary
    
    mkdir -p "$(dirname "$TOKEN_FILE")"
    
    log "Running your-pdv-serviceauth (browser will open for Okta login)..."
    
    if "$PDV_AUTH_BIN"; then
        if [[ -f "$TOKEN_FILE" ]]; then
            STATUS=$(check_token)
            log_success "Token refreshed successfully! Status: $STATUS"
            return 0
        else
            log_error "your-pdv-serviceauth completed but token file not created"
            return 1
        fi
    else
        log_error "your-pdv-serviceauth failed"
        return 1
    fi
}

# Main
main() {
    case "${1:-}" in
        --check)
            STATUS=$(check_token)
            case "$STATUS" in
                NO_TOKEN)
                    log_warning "No token file found at $TOKEN_FILE"
                    log "Run: $0 to create one"
                    exit 1
                    ;;
                INVALID)
                    log_error "Token is invalid"
                    exit 1
                    ;;
                EXPIRED)
                    log_error "Token has expired"
                    log "Run: $0 to refresh"
                    exit 1
                    ;;
                EXPIRING_SOON)
                    log_warning "Token expires in less than 1 hour"
                    log "Run: $0 to refresh"
                    exit 0
                    ;;
                VALID:*)
                    HOURS=${STATUS#VALID:}
                    log_success "Token is valid for $HOURS"
                    exit 0
                    ;;
            esac
            ;;
        --cron)
            # For cron job - check and refresh if needed
            BACKEND_URL="${BACKEND_URL:-http://localhost:8000}"
            PDV_SLACK_CHANNEL="${PDV_SLACK_CHANNEL:-YOUR_SLACK_CHANNEL_ID}"
            
            STATUS=$(check_token)
            case "$STATUS" in
                VALID:*)
                    HOURS=${STATUS#VALID:}
                    log "Token valid for $HOURS - no refresh needed"
                    ;;
                *)
                    log_warning "Token status: $STATUS - refresh needed"
                    log_error "Cannot refresh automatically (requires browser login)"
                    log "Please run manually: $0"
                    
                    # Send Slack notification via backend API
                    ALERT_MSG="⚠️ *PDV Token Expired*\nStatus: ${STATUS}\nAction: Run \`your-pdv-serviceauth\` on the VM to refresh"
                    curl -s -X POST "${BACKEND_URL}/api/slack/send" \
                        -H 'Content-type: application/json' \
                        -d "{\"channel\":\"${PDV_SLACK_CHANNEL}\",\"message\":\"${ALERT_MSG}\"}" \
                        || log_warning "Failed to send Slack alert"
                    
                    exit 1
                    ;;
            esac
            ;;
        --help|-h)
            echo "Usage: $0 [--check|--cron|--help]"
            echo ""
            echo "Options:"
            echo "  (none)    Refresh token (opens browser for Okta login)"
            echo "  --check   Check token status"
            echo "  --cron    For cron job (check and alert if expired)"
            echo "  --help    Show this help"
            ;;
        *)
            # Default: refresh token
            STATUS=$(check_token)
            case "$STATUS" in
                VALID:*)
                    HOURS=${STATUS#VALID:}
                    log "Current token valid for $HOURS"
                    read -p "Refresh anyway? [y/N] " -n 1 -r
                    echo
                    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
                        exit 0
                    fi
                    ;;
            esac
            refresh_token
            ;;
    esac
}

main "$@"
