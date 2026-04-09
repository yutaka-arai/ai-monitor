#!/bin/bash

SESSION="dev"
MONITOR_DIR="$HOME/ai-monitor"
VENV_PYTHON="$MONITOR_DIR/.venv/bin/python"
ENV_FILE="$MONITOR_DIR/.env"
LEGACY_ENV_FILE="$HOME/claude-monitor/.env"

if [ -x "$VENV_PYTHON" ]; then
  PYTHON_CMD="$VENV_PYTHON"
else
  PYTHON_CMD="python3"
fi

if [ -f "$ENV_FILE" ]; then
  MONITOR_CMD="set -a && source '$ENV_FILE' && set +a && '$PYTHON_CMD' monitor.py"
elif [ -f "$LEGACY_ENV_FILE" ]; then
  MONITOR_CMD="set -a && source '$LEGACY_ENV_FILE' && set +a && '$PYTHON_CMD' monitor.py"
else
  MONITOR_CMD="'$PYTHON_CMD' monitor.py"
fi

# 既存セッションがあれば削除して新規作成
tmux kill-session -t "$SESSION" 2>/dev/null

tmux new-session -d -s "$SESSION" -x "$(tput cols)" -y "$(tput lines)"

# 上ペイン: monitor.py を起動
tmux send-keys -t "$SESSION" "cd '$MONITOR_DIR' && $MONITOR_CMD" Enter

# 上下に分割（上70% / 下30%）
tmux split-window -v -p 30 -t "$SESSION"

# 下ペイン: Claude Code を起動
tmux send-keys -t "$SESSION" "claude" Enter

# セッションにアタッチ
tmux attach-session -t "$SESSION"
