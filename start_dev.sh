#!/bin/bash

SESSION="dev"
MONITOR_DIR="$HOME/ai-monitor"
SYNC_SCRIPT="$MONITOR_DIR/sync_claude_usage.py"
VENV_PYTHON="$MONITOR_DIR/.venv/bin/python"
ENV_FILE="$MONITOR_DIR/.env"
LEGACY_ENV_FILE="$HOME/claude-monitor/.env"

if [ -x "$VENV_PYTHON" ]; then
  PYTHON_CMD="$VENV_PYTHON"
else
  PYTHON_CMD="python3"
fi

if [ -f "$ENV_FILE" ]; then
  ENV_SOURCE_CMD="set -a && source '$ENV_FILE' && set +a && "
elif [ -f "$LEGACY_ENV_FILE" ]; then
  ENV_SOURCE_CMD="set -a && source '$LEGACY_ENV_FILE' && set +a && "
else
  ENV_SOURCE_CMD=""
fi

MONITOR_CMD="${ENV_SOURCE_CMD}'$PYTHON_CMD' monitor.py"

# 既存セッションがあれば削除して新規作成
tmux kill-session -t "$SESSION" 2>/dev/null

tmux new-session -d -s "$SESSION" -x "$(tput cols)" -y "$(tput lines)"

# 上ペイン: この ai-monitor 用の sync_claude_usage.py が既に動作していなければ起動し、monitor.py を起動
# （このリポジトリの絶対パスで pgrep するため、他ディレクトリの同名スクリプトは対象にならない）
tmux send-keys -t "$SESSION" "cd '$MONITOR_DIR' && { pgrep -f '$SYNC_SCRIPT' >/dev/null 2>&1 || (nohup '$PYTHON_CMD' '$SYNC_SCRIPT' >> sync_claude_usage.log 2>&1 &) ; } && $MONITOR_CMD" Enter

# 上下に分割（上70% / 下30%）
tmux split-window -v -p 30 -t "$SESSION"

# 下ペイン: Claude Code を起動
tmux send-keys -t "$SESSION" "cd '$MONITOR_DIR' && claude" Enter

# セッションにアタッチ
tmux attach-session -t "$SESSION"
