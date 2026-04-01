import json
import os
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

CLAUDE_DIR  = Path.home() / ".claude" / "projects"
OUTPUT_FILE = Path(__file__).parent / "claude_usage_log.json"
INTERVAL    = 5  # 更新間隔（秒）


def scan_and_aggregate() -> dict:
    """~/.claude/projects 以下の全 JSONL を走査し、当月分を集計して返す。"""
    now         = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # model → 累計トークン数
    model_totals: dict[str, dict] = defaultdict(lambda: {
        "uncached_input_tokens":   0,
        "output_tokens":           0,
        "cache_read_input_tokens": 0,
        "cache_creation": {
            "ephemeral_1h_input_tokens": 0,
            "ephemeral_5m_input_tokens": 0,
        },
    })

    for jsonl_path in CLAUDE_DIR.rglob("*.jsonl"):
        try:
            with open(jsonl_path, encoding="utf-8", errors="replace") as f:
                for raw in f:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        entry = json.loads(raw)
                    except json.JSONDecodeError:
                        continue

                    msg = entry.get("message")
                    if not isinstance(msg, dict):
                        continue
                    if msg.get("role") != "assistant":
                        continue
                    usage = msg.get("usage")
                    if not usage:
                        continue

                    # 当月フィルタ（timestamp がない行は含める）
                    ts = entry.get("timestamp")
                    if ts:
                        try:
                            entry_dt = datetime.fromisoformat(
                                ts.replace("Z", "+00:00")
                            )
                            if entry_dt < month_start:
                                continue
                        except ValueError:
                            pass

                    model = msg.get("model", "unknown")
                    cc    = usage.get("cache_creation") or {}
                    t     = model_totals[model]

                    t["uncached_input_tokens"]                    += usage.get("input_tokens", 0)
                    t["output_tokens"]                            += usage.get("output_tokens", 0)
                    t["cache_read_input_tokens"]                  += usage.get("cache_read_input_tokens", 0)
                    t["cache_creation"]["ephemeral_1h_input_tokens"] += cc.get("ephemeral_1h_input_tokens", 0)
                    t["cache_creation"]["ephemeral_5m_input_tokens"] += cc.get("ephemeral_5m_input_tokens", 0)

        except Exception:
            continue

    results = [{"model": model, **totals} for model, totals in sorted(model_totals.items())]
    return {"data": [{"results": results}]}


def main():
    print(f"[sync] 開始  出力先: {OUTPUT_FILE}  更新間隔: {INTERVAL}秒")
    print(f"[sync] 読み込み元: {CLAUDE_DIR}")
    while True:
        try:
            data    = scan_and_aggregate()
            results = data["data"][0]["results"]

            with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            total_input  = sum(r["uncached_input_tokens"] for r in results)
            total_output = sum(r["output_tokens"]          for r in results)
            ts_str       = datetime.now().strftime("%H:%M:%S")
            models_str   = ", ".join(r["model"] for r in results) or "なし"
            print(
                f"[{ts_str}] 更新完了  "
                f"input={total_input:,}  output={total_output:,}  "
                f"モデル: {models_str}"
            )

        except Exception as e:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] エラー: {e}")

        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
