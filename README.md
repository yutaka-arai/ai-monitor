# ai-monitor

Terminal dashboard for monitoring Claude usage from a local JSON log and checking OpenAI / Gemini connectivity.

This repository is designed to run on Raspberry Pi and Ubuntu with the same codebase.

## Requirements

- Python 3.10+
- `tmux`
- Network access for OpenAI / Gemini connectivity checks
- Optional: Claude Code CLI available as `claude` if you want to use `start_dev.sh`

## Files

- `monitor.py`: dashboard UI
- `sync_claude_usage.py`: updates `claude_usage_log.json` from local Claude Code logs
- `start_dev.sh`: launches the dashboard in the top tmux pane and `claude` in the bottom pane

## Setup

```bash
git clone <your-repo-url>
cd ai-monitor
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
chmod +x start_dev.sh
```

Set any API keys you want to use in `.env`.

- `OPENAI_API_KEY`: enables OpenAI connectivity checks
- `GOOGLE_API_KEY`: enables Gemini connectivity checks

If a key is missing, the corresponding panel stays in a disconnected state. The dashboard still runs.

## Ubuntu Notes

No code changes should be required on Ubuntu if the following are true:

- `python3` is installed
- `tmux` is installed
- dependencies from `requirements.txt` are installed
- optional API keys are set in `.env`
- optional `claude` CLI is installed if you use `start_dev.sh`

If Ubuntu does not have the `claude` command, run the dashboard directly instead of `start_dev.sh`:

```bash
cd ai-monitor
. .venv/bin/activate
python monitor.py
```

## Claude Usage Log

The Claude panel reads from:

```text
claude_usage_log.json
```

If you want Claude usage metrics, generate or refresh that file with:

```bash
cd ai-monitor
. .venv/bin/activate
python sync_claude_usage.py
```

If the log file does not exist, the dashboard still starts, but the Claude panel shows an error message.

## Run

Direct run:

```bash
cd ai-monitor
. .venv/bin/activate
python monitor.py
```

tmux launcher:

```bash
./start_dev.sh
```

## GitHub Publishing

Safe to commit:

- `monitor.py`
- `sync_claude_usage.py`
- `start_dev.sh`
- `requirements.txt`
- `README.md`
- `.env.example`

Do not commit:

- `.env`
- `claude_usage_log.json`
- `sync.log`
- virtualenv contents
