import json
import math
import os
import re
import subprocess
import time
from datetime import datetime, timedelta, timezone

from google import genai
import requests
from dotenv import load_dotenv
from rich.console import Console, Group
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

load_dotenv()

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "claude_usage_log.json")

REFRESH_INTERVAL = 5  # seconds
BAR_WIDTH        = 20  # 横並び用コンパクトバー幅

# Claude: 月間トークン基準上限
TOKEN_LIMITS = {
    "input_tokens":                100_000,
    "output_tokens":                50_000,
    "cache_creation_input_tokens": 100_000,
    "cache_read_input_tokens":     100_000,
}

# OpenAI: セッション累計基準上限
OPENAI_TOKEN_LIMIT = 10_000

# ── セッション統計 ────────────────────────────────────────────────────────────

# Claude: 起動時のベースライン（差分計算用）
claude_baseline: dict | None = None

gemini_session_stats = {
    "total_requests": 0,
    "total_prompt_tokens": 0,
    "total_response_tokens": 0,
    "total_tokens": 0,
}

openai_session_stats = {
    "total_requests": 0,
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "total_tokens": 0,
}

console = Console()


# ── 共通ウィジェット ──────────────────────────────────────────────────────────

def dynamic_limit(used: int, base: int) -> int:
    if used >= base:
        return max(base, int(used * 1.2) + 1)
    return base


def make_bar(label: str, used: int, base_limit: int, color: str) -> Text:
    limit  = dynamic_limit(used, base_limit)
    pct    = used / limit if limit > 0 else 0
    filled = math.ceil(pct * BAR_WIDTH) if used > 0 else 0
    filled = min(filled, BAR_WIDTH)

    bar        = f"[{color}]" + "█" * filled + "[/]" + "░" * (BAR_WIDTH - filled)
    auto_mark  = "" if limit == base_limit else " ~"
    pct_str    = f"{min(pct, 1.0) * 100:.0f}%"

    text = Text()
    text.append(f"{label}\n", style="bold white")
    text.append(bar)
    text.append(f"\n  {used:,} / {limit:,}{auto_mark}  {pct_str}", style="dim")
    return text


# ── Claude ───────────────────────────────────────────────────────────────────

def load_usage_from_log() -> tuple[dict | None, str | None, str | None]:
    """ローカルの claude_usage_log.json を読み込む。
    戻り値: (data, log_time_str, error_msg)
    """
    if not os.path.exists(LOG_FILE):
        return None, None, f"ログファイルが見つかりません: {os.path.basename(LOG_FILE)}"
    try:
        mtime = os.path.getmtime(LOG_FILE)
        log_time_str = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
        with open(LOG_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data, log_time_str, None
    except json.JSONDecodeError as e:
        return None, None, f"JSON パースエラー: {e}"
    except Exception as e:
        return None, None, f"読み込みエラー: {e}"


def aggregate_usage(data: dict) -> tuple[dict, list]:
    totals = {k: 0 for k in TOKEN_LIMITS}
    flat   = []
    for bucket in data.get("data", []):
        for r in bucket.get("results", []):
            cc = r.get("cache_creation") or {}
            entry = {
                "model":                       r.get("model", "unknown"),
                "input_tokens":                r.get("uncached_input_tokens", 0),
                "output_tokens":               r.get("output_tokens", 0),
                "cache_creation_input_tokens": (
                    cc.get("ephemeral_1h_input_tokens", 0)
                    + cc.get("ephemeral_5m_input_tokens", 0)
                ),
                "cache_read_input_tokens":     r.get("cache_read_input_tokens", 0),
            }
            flat.append(entry)
            for k in totals:
                totals[k] += entry[k]
    return totals, flat


def _session_diff(totals: dict, baseline: dict | None, key: str) -> str:
    if baseline is None:
        return ""
    diff = totals.get(key, 0) - baseline.get(key, 0)
    return f"  [dim cyan]↑ セッション: +{diff:,}[/dim cyan]"


def build_claude_panel(totals: dict, error_msg: str | None, baseline: dict | None, log_time: str | None = None) -> Panel:
    g = Table.grid(padding=(0, 1))
    g.add_column(ratio=1)

    if error_msg:
        g.add_row(Text(f"[red]{error_msg}[/red]"))
    else:
        for label, key, limit, color in [
            ("Input",      "input_tokens",                100_000, "green"),
            ("Output",     "output_tokens",                50_000, "yellow"),
            ("Cache Cre.", "cache_creation_input_tokens", 100_000, "blue"),
            ("Cache Read", "cache_read_input_tokens",     100_000, "magenta"),
        ]:
            g.add_row(make_bar(label, totals.get(key, 0), limit, color))
            diff_str = _session_diff(totals, baseline, key)
            if diff_str:
                g.add_row(Text.from_markup(diff_str))
            g.add_row(Text(""))

        total_all = sum(totals.values())
        session_total = (
            sum(totals.get(k, 0) - baseline.get(k, 0) for k in TOKEN_LIMITS)
            if baseline else None
        )
        summary = Text()
        summary.append(f"月間合計: {total_all:,} tokens", style="bold white")
        if session_total is not None:
            summary.append(f"  [dim cyan]↑ セッション: +{session_total:,}[/dim cyan]")
        g.add_row(summary)
        if log_time:
            g.add_row(Text(f"ログ更新: {log_time}", style="dim"))

    return Panel(g, title="[bold cyan]Claude[/bold cyan]", border_style="cyan", padding=(0, 1))


# ── OpenAI ───────────────────────────────────────────────────────────────────

def fetch_openai_status() -> dict:
    if not OPENAI_API_KEY:
        return {
            "connected": False,
            "error": "OPENAI_API_KEY 未設定",
            "models": [],
            "last_checked": datetime.now().strftime("%H:%M:%S"),
        }

    try:
        resp = requests.get(
            "https://api.openai.com/v1/models",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
            timeout=10,
        )
        resp.raise_for_status()
        models = sorted(m["id"] for m in resp.json().get("data", []))
        openai_session_stats["total_requests"] += 1
        return {
            "connected": True,
            "error": None,
            "models": models,
            "last_checked": datetime.now().strftime("%H:%M:%S"),
        }
    except requests.exceptions.HTTPError as e:
        code = e.response.status_code if e.response is not None else "?"
        return {
            "connected": False,
            "error": f"HTTP {code}",
            "models": [],
            "last_checked": datetime.now().strftime("%H:%M:%S"),
        }
    except requests.exceptions.RequestException as e:
        return {
            "connected": False,
            "error": str(e),
            "models": [],
            "last_checked": datetime.now().strftime("%H:%M:%S"),
        }


def build_openai_panel(status: dict, stats: dict) -> Panel:
    g = Table.grid(padding=(0, 1))
    g.add_column(ratio=1)

    if not status["connected"]:
        g.add_row(Text(f"[red]✗ {status.get('error', '接続失敗')}[/red]"))
    else:
        g.add_row(Text("[bold green]✓ 接続済み[/bold green]"))

    g.add_row(Text(""))

    tbl = Table(show_header=False, box=None, padding=(0, 1))
    tbl.add_column(style="dim", no_wrap=True)
    tbl.add_column(justify="right", style="bold white")
    tbl.add_row("Status checks", f"{stats['total_requests']:,}")
    tbl.add_row("Models", f"{len(status.get('models', [])):,}")
    tbl.add_row("Last checked", status.get("last_checked", "-"))
    g.add_row(tbl)

    g.add_row(Text(""))
    g.add_row(Text("Token usage: 未計測", style="dim"))
    g.add_row(Text("このパネルは接続確認のみ実施", style="dim"))

    return Panel(g, title="[bold yellow]OpenAI[/bold yellow]", border_style="yellow", padding=(0, 1))


# ── Gemini ───────────────────────────────────────────────────────────────────

def fetch_gemini_info() -> tuple[list, str | None]:
    if not GOOGLE_API_KEY:
        return [], "GOOGLE_API_KEY 未設定"
    try:
        client = genai.Client(api_key=GOOGLE_API_KEY)
        models = list(client.models.list())
        gemini_session_stats["total_requests"] += 1
        return models, None
    except Exception as e:
        return [], str(e)


def build_gemini_panel(models: list, stats: dict, error_msg: str | None) -> Panel:
    g = Table.grid(padding=(0, 1))
    g.add_column(ratio=1)

    if error_msg:
        g.add_row(Text(f"[red]✗ {error_msg}[/red]"))
    else:
        g.add_row(Text("[bold green]✓ 接続済み[/bold green]"))
        g.add_row(Text(""))

        tbl = Table(show_header=False, box=None, padding=(0, 1))
        tbl.add_column(style="dim", no_wrap=True)
        tbl.add_column(justify="right", style="bold white")
        tbl.add_row("Requests",  f"{stats['total_requests']:,}")
        tbl.add_row("Prompt tk", f"{stats['total_prompt_tokens']:,}")
        tbl.add_row("Resp tk",   f"{stats['total_response_tokens']:,}")
        tbl.add_row("Total tk",  f"{stats['total_tokens']:,}")
        g.add_row(tbl)
        g.add_row(Text(""))

        if models:
            g.add_row(Text(f"Models: {len(models)}", style="dim"))

    return Panel(g, title="[bold green]Gemini[/bold green]", border_style="green", padding=(0, 1))


# ── GitHub Copilot ───────────────────────────────────────────────────────────

# ── GitHub Copilot ───────────────────────────────────────────────────────────

# ── GitHub Copilot ───────────────────────────────────────────────────────────

_copilot_version_cache: str | None = None  # 起動後1回だけ取得してキャッシュ


def fetch_copilot_info() -> dict:
    """gh CLI を使って Copilot の認証状態とバージョンを取得する。"""
    global _copilot_version_cache

    info = {
        "username":    "yutaka-arai",
        "auth_status": None,
        "active":      False,
        "version":     _copilot_version_cache,
        "error":       None,
    }

    # gh auth status（毎回実行・高速）
    try:
        result = subprocess.run(
            ["gh", "auth", "status"],
            capture_output=True, text=True, timeout=5,
        )
        output = result.stdout + result.stderr
        for line in output.splitlines():
            if "Logged in to" in line:
                info["auth_status"] = line.strip().lstrip("✓ ").strip()
                info["active"] = True
                m = re.search(r"account\s+(\S+)", line)
                if m:
                    info["username"] = m.group(1)
                break
    except Exception as e:
        info["error"] = f"gh auth status: {e}"

    # gh copilot --version（初回のみ取得・低速なのでキャッシュ）
    if _copilot_version_cache is None:
        try:
            result = subprocess.run(
                ["gh", "copilot", "--version"],
                capture_output=True, text=True, timeout=15,
            )
            first_line = (result.stdout or result.stderr).splitlines()[0].rstrip(".")
            _copilot_version_cache = first_line.strip()
            info["version"] = _copilot_version_cache
        except Exception as e:
            if info["error"] is None:
                info["error"] = f"gh copilot --version: {e}"

    return info


def build_copilot_panel(info: dict) -> Panel:
    g = Table.grid(padding=(0, 1))
    g.add_column(ratio=1)

    if info["active"]:
        g.add_row(Text("✓ 個人プランで稼働中", style="bold green"))
    else:
        g.add_row(Text("✗ 未認証", style="bold red"))

    g.add_row(Text(""))

    tbl = Table(show_header=False, box=None, padding=(0, 1))
    tbl.add_column(style="dim", no_wrap=True)
    tbl.add_column(style="bold white")
    tbl.add_row("ユーザー名", info["username"] or "-")
    tbl.add_row("認証状態",   info["auth_status"] or "[dim]取得中...[/dim]")
    tbl.add_row("バージョン", info["version"]     or "[dim]取得中...[/dim]")
    g.add_row(tbl)

    if info["error"]:
        g.add_row(Text(""))
        g.add_row(Text(f"⚠ {info['error']}", style="dim yellow"))

    return Panel(
        g,
        title="[bold magenta]GitHub Copilot[/bold magenta]",
        border_style="magenta",
        padding=(0, 1),
    )




def build_display(
    claude_panel: Panel,
    openai_panel: Panel,
    gemini_panel: Panel,
    copilot_panel: Panel,
    now_str: str,
    countdown: int,
) -> Layout:
    header = Text(
        f"最終更新: {now_str}  |  次の更新まで {countdown:2d} 秒  |  Ctrl+C で終了",
        style="dim",
        justify="center",
    )

    top_row = Layout(name="top_row")
    top_row.split_row(
        Layout(claude_panel,  name="claude",  minimum_size=28),
        Layout(openai_panel,  name="openai",  minimum_size=28),
    )

    bot_row = Layout(name="bot_row")
    bot_row.split_row(
        Layout(gemini_panel,  name="gemini",  minimum_size=28),
        Layout(copilot_panel, name="copilot", minimum_size=28),
    )

    panels = Layout(name="panels", minimum_size=30)
    panels.split_column(top_row, bot_row)

    root = Layout()
    root.split_column(
        Layout(header, name="header", size=1),
        panels,
    )
    return root


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    global claude_baseline
    console.print("[bold cyan]Claude / OpenAI / Gemini / Copilot モニターを起動中...[/bold cyan]")

    # 他サービスの結果をループ間で保持（初回サイクルで取得されるまでの暫定値）
    openai_status: dict = {"connected": False, "error": "取得中..."}
    gemini_models: list = []
    gemini_error: str | None = "取得中..."
    copilot_info: dict = {
        "username": "", "auth_status": None, "active": False,
        "version": None, "error": None,
    }
    refresh_other = True  # 初回は他サービスも必ず取得する

    with Live(console=console, refresh_per_second=1, screen=True) as live:
        while True:
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            # Claude: ログファイルを毎ループ読み込み（ローカル・高速）
            claude_data, claude_log_time, claude_error = load_usage_from_log()
            if claude_data is not None:
                totals, entries = aggregate_usage(claude_data)
                # 起動後の初回成功取得をベースラインとして保存
                if claude_baseline is None:
                    claude_baseline = dict(totals)
            else:
                totals, entries = {k: 0 for k in TOKEN_LIMITS}, []
                claude_log_time = None

            # ログファイルの現在の mtime を記録（変更検知用）
            try:
                log_mtime = os.path.getmtime(LOG_FILE)
            except OSError:
                log_mtime = None

            # 他サービスは60秒の通常サイクル完了時のみ更新
            # （ファイル変更によるリロード時はスキップして即時表示を優先）
            if refresh_other:
                openai_status  = fetch_openai_status()
                gemini_models, gemini_error = fetch_gemini_info()
                copilot_info = fetch_copilot_info()

            def _make_display(countdown: int) -> Layout:
                return build_display(
                    build_claude_panel(totals, claude_error, claude_baseline, claude_log_time),
                    build_openai_panel(openai_status, dict(openai_session_stats)),
                    build_gemini_panel(gemini_models, dict(gemini_session_stats), gemini_error),
                    build_copilot_panel(copilot_info),
                    now_str, countdown,
                )

            live.update(_make_display(REFRESH_INTERVAL))

            # カウントダウン更新（ファイル変更を検知したら即座にリロード）
            for remaining in range(REFRESH_INTERVAL, 0, -1):
                time.sleep(1)
                try:
                    current_mtime = os.path.getmtime(LOG_FILE)
                except OSError:
                    current_mtime = None
                if current_mtime != log_mtime:
                    refresh_other = False  # ファイル変更リロード：他サービスはスキップ
                    break
                live.update(_make_display(remaining))
            else:
                refresh_other = True  # 60秒完走：次サイクルで他サービスも更新


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n[bold yellow]モニターを終了しました。[/bold yellow]")
