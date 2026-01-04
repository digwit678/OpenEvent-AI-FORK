#!/usr/bin/env bash
#
# PERMANENT FIX for port 8000 issues
# This script ALWAYS cleans up before starting the backend
#
# Usage:
#   ./scripts/dev/dev_server.sh         # Start backend
#   ./scripts/dev/dev_server.sh stop    # Stop backend
#   ./scripts/dev/dev_server.sh restart # Restart backend
#
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

PORT=8000
PID_FILE=".dev/backend.pid"
FRONTEND_PORT=3000
FRONTEND_PID_FILE=".dev/frontend.pid"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() { echo -e "${GREEN}[DEV]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[DEV]${NC} $1"; }
log_error() { echo -e "${RED}[DEV]${NC} $1"; }

# Ensure .dev directory exists
mkdir -p .dev

kill_port() {
    local port=$1
    local pids=$(lsof -nP -iTCP:$port -sTCP:LISTEN -t 2>/dev/null || true)
    if [ -n "$pids" ]; then
        log_warn "Killing processes on port $port: $pids"
        echo "$pids" | xargs kill -9 2>/dev/null || true
        sleep 1
    fi
}

kill_pid_file() {
    local pid_file=$1
    if [ -f "$pid_file" ]; then
        local old_pid=$(cat "$pid_file" 2>/dev/null || true)
        if [ -n "$old_pid" ] && kill -0 "$old_pid" 2>/dev/null; then
            log_warn "Killing old process from $pid_file (PID: $old_pid)"
            kill -9 "$old_pid" 2>/dev/null || true
            sleep 1
        fi
        rm -f "$pid_file"
    fi
}

cleanup_backend() {
    log_info "Cleaning up backend..."
    kill_pid_file "$PID_FILE"
    kill_port $PORT
    log_info "Backend cleanup complete"
}

cleanup_frontend() {
    log_info "Cleaning up frontend..."
    kill_pid_file "$FRONTEND_PID_FILE"
    kill_port $FRONTEND_PORT
    log_info "Frontend cleanup complete"
}

start_backend() {
    # ALWAYS cleanup first - this is the permanent fix
    cleanup_backend

    # Verify port is free
    if lsof -nP -iTCP:$PORT -sTCP:LISTEN -t >/dev/null 2>&1; then
        log_error "Port $PORT still in use after cleanup!"
        log_error "Manual intervention required: lsof -nP -tiTCP:$PORT -sTCP:LISTEN | xargs kill -9"
        exit 1
    fi

    # Load API keys from Keychain
    OPENAI_KEY_SERVICE='openevent-api-test-key'
    if security find-generic-password -s "$OPENAI_KEY_SERVICE" -a "$USER" >/dev/null 2>&1; then
        export OPENAI_API_KEY="$(security find-generic-password -a "$USER" -s "$OPENAI_KEY_SERVICE" -w)"
        log_info "Loaded OPENAI_API_KEY from Keychain"
    else
        log_warn "No Keychain item '$OPENAI_KEY_SERVICE' - running without OpenAI"
    fi

    GEMINI_KEY_SERVICE='openevent-gemini-key'
    if security find-generic-password -s "$GEMINI_KEY_SERVICE" >/dev/null 2>&1; then
        export GOOGLE_API_KEY="$(security find-generic-password -s "$GEMINI_KEY_SERVICE" -w)"
        log_info "Loaded GOOGLE_API_KEY from Keychain"
    else
        log_warn "No Keychain item '$GEMINI_KEY_SERVICE' - running without Gemini"
    fi

    # Set environment
    export PYTHONPATH="$(pwd)"
    export PYTHONDONTWRITEBYTECODE=1
    export TZ=Europe/Zurich
    # Default to gemini mode for hybrid setup
    export AGENT_MODE="${AGENT_MODE:-gemini}"
    # Detection mode: unified uses both Gemini (intent) and OpenAI (verbalization)
    export DETECTION_MODE="${DETECTION_MODE:-unified}"
    # Fallback diagnostics: off by default (set to 1 for debugging)
    export OE_FALLBACK_DIAGNOSTICS="${OE_FALLBACK_DIAGNOSTICS:-0}"
    # Enable dangerous endpoints for dev/testing (reset client, clear tasks, etc.)
    export ENABLE_DANGEROUS_ENDPOINTS="${ENABLE_DANGEROUS_ENDPOINTS:-true}"
    # Enable tenant header switching for multi-tenancy testing
    export TENANT_HEADER_ENABLED="${TENANT_HEADER_ENABLED:-1}"

    # ========== API KEY STATUS CHECK ==========
    echo ""
    echo "=========================================="
    echo "          API KEY STATUS"
    echo "=========================================="
    if [ -n "${OPENAI_API_KEY:-}" ]; then
        echo -e "${GREEN}✓ OPENAI_API_KEY${NC}: SET (${#OPENAI_API_KEY} chars)"
    else
        echo -e "${RED}✗ OPENAI_API_KEY${NC}: NOT SET - verbalization will fail!"
    fi
    if [ -n "${GOOGLE_API_KEY:-}" ]; then
        echo -e "${GREEN}✓ GOOGLE_API_KEY${NC}: SET (${#GOOGLE_API_KEY} chars)"
    else
        echo -e "${RED}✗ GOOGLE_API_KEY${NC}: NOT SET - Gemini detection will fail!"
    fi
    echo "------------------------------------------"
    echo "AGENT_MODE: $AGENT_MODE"
    echo "DETECTION_MODE: ${DETECTION_MODE:-legacy}"
    echo "=========================================="
    echo ""

    # Warn if hybrid mode but keys missing
    if [ "$AGENT_MODE" = "gemini" ] && [ -z "${GOOGLE_API_KEY:-}" ]; then
        log_error "AGENT_MODE=gemini but GOOGLE_API_KEY is not set!"
        log_error "Add key to Keychain: security add-generic-password -s 'openevent-gemini-key' -a '$USER' -w 'YOUR_KEY'"
        exit 1
    fi

    log_info "Starting backend on port $PORT..."

    # Start uvicorn in background and capture PID
    uvicorn backend.main:app --reload --port $PORT &
    local new_pid=$!
    echo "$new_pid" > "$PID_FILE"

    log_info "Backend started with PID $new_pid (saved to $PID_FILE)"

    # Wait a moment and verify it's running
    sleep 2
    if ! kill -0 "$new_pid" 2>/dev/null; then
        log_error "Backend failed to start!"
        rm -f "$PID_FILE"
        exit 1
    fi

    log_info "Backend running at http://localhost:$PORT"
}

stop_backend() {
    cleanup_backend
    log_info "Backend stopped"
}

status() {
    echo "=== Backend Status ==="
    if [ -f "$PID_FILE" ]; then
        local pid=$(cat "$PID_FILE")
        if kill -0 "$pid" 2>/dev/null; then
            log_info "Backend running (PID: $pid)"
        else
            log_warn "PID file exists but process not running"
        fi
    else
        log_warn "No PID file found"
    fi

    local port_pids=$(lsof -nP -iTCP:$PORT -sTCP:LISTEN -t 2>/dev/null || true)
    if [ -n "$port_pids" ]; then
        log_info "Port $PORT in use by: $port_pids"
    else
        log_warn "Port $PORT is free"
    fi
}

case "${1:-start}" in
    start)
        start_backend
        ;;
    stop)
        stop_backend
        ;;
    restart)
        stop_backend
        start_backend
        ;;
    status)
        status
        ;;
    cleanup)
        cleanup_backend
        cleanup_frontend
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status|cleanup}"
        exit 1
        ;;
esac
