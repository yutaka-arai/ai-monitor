#!/bin/bash

SESSION="dev"
MONITOR_DIR="$HOME/claude-monitor"

# 既存セッションがあれば削除して新規作成
tmux kill-session -t "$SESSION" 2>/dev/null

tmux new-session -d -s "$SESSION" -x "$(tput cols)" -y "$(tput lines)"

# 上ペイン: monitor.py を起動
tmux send-keys -t "$SESSION" "cd '$MONITOR_DIR' && python monitor.py" Enter

# 上下に分割（上70% / 下30%）
tmux split-window -v -p 30 -t "$SESSION"

# 下ペイン: Claude Code を起動
tmux send-keys -t "$SESSION" "claude" Enter

# セッションにアタッチ
tmux attach-session -t "$SESSION"
