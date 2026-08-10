#!/bin/bash

SESSION="dev"
MONITOR_DIR="$HOME/ai-monitor"
SYNC_SCRIPT="$MONITOR_DIR/sync_claude_usage.py"

# 既存セッションがあれば削除して新規作成
tmux kill-session -t "$SESSION" 2>/dev/null

tmux new-session -d -s "$SESSION" -x "$(tput cols)" -y "$(tput lines)"

# 上ペイン: この ai-monitor 用の sync_claude_usage.py が既に動作していなければ起動し、monitor.py を起動
# （このリポジトリの絶対パスで pgrep するため、他ディレクトリの同名スクリプトは対象にならない）
tmux send-keys -t "$SESSION" "cd '$MONITOR_DIR' && source .venv/bin/activate && { pgrep -f '$SYNC_SCRIPT' >/dev/null 2>&1 || (nohup python '$SYNC_SCRIPT' >> sync_claude_usage.log 2>&1 &) ; } && python monitor.py" Enter

# 上下に分割（上70% / 下30%）
tmux split-window -v -p 30 -t "$SESSION"

# 下ペイン: Claude Code を起動
tmux send-keys -t "$SESSION" "cd '$MONITOR_DIR' && claude" Enter

# セッションにアタッチ
tmux attach-session -t "$SESSION"
