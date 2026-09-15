# Telegram Media Forwarder

A collection of Python scripts, built on [Telethon](https://github.com/LonamiWebs/Telethon), for automatically forwarding photos, videos, and files between Telegram chats, channels, or groups. Old media is backfilled in bulk, new media is forwarded in real time, and duplicates are always skipped.

Beyond the original single-account forwarder, this repo now includes a **multi-account mode** that automatically rotates between Telegram accounts when one hits a `FloodWait`, so a large backfill can keep running instead of sitting idle, plus a **smart-fill mode** that diffs a source against a target and only forwards what's actually missing.

## Features

- Forwards all existing media from a source chat to a target chat, then switches to live listening for new messages
- Skips duplicates via a persistent `forwarded_ids.txt` log
- Resumes automatically after a crash or restart using a saved checkpoint
- Groups albums (multiple photos/videos sent together) and forwards them as a single album instead of separate messages
- Handles Telegram's `FloodWait` rate limiting automatically
- **Multi-account rotation**: when an account is flood-waited, forwarding continues on the next account in the pool instead of stopping
- **Smart-fill**: scans the target channel first, builds a set of media already present, and forwards only what's missing from the source — no re-sending duplicates on a partially-filled target
- Works with usernames, numeric chat IDs, or phone numbers as source/target

## Project structure

| File | Purpose |
|---|---|
| `config.py` | Shared configuration — `SOURCE`, `TARGET`, and the `ACCOUNTS` pool used by every script |
| `login_accounts.py` | One-time helper that logs in every account in `ACCOUNTS` and saves its session file |
| `AccountSwitch_Media_Forwarder.py` | Main forwarder — backfills old media, then listens live, rotating accounts on `FloodWait` |
| `SmartFill_Forwarder.py` | Diff-based forwarder — scans the target, then forwards only media missing from it |
| `OneClick_Media_Forward.py` | Simple single-account forwarder for smaller jobs that don't need account rotation |

## Requirements

- Python 3.7+
- [Telethon](https://docs.telethon.dev/)

```bash
pip install telethon
```

## Getting Telegram API credentials

1. Go to [my.telegram.org](https://my.telegram.org) and log in with your phone number.
2. Open **API Development Tools** and create an application.
3. Note down the `api_id` and `api_hash` — you'll need one pair per account you want to use.

## Configuration

All scripts read from `config.py`. Fill it in once:

```python
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Source and target chats — username, numeric ID, or phone number
SOURCE = "source_chat_username_or_id"
TARGET = "target_chat_username_or_id"

# Account pool — add one or more accounts here.
# A single account works fine; add more to enable flood-wait rotation.
ACCOUNTS = [
    {
        "name": "account1",
        "api_id": 123456,
        "api_hash": "your_api_hash_here",
        "session": os.path.join(BASE_DIR, "session_account1"),
    },
    # Add more accounts to enable automatic rotation on FloodWait
]
```
## Usage

### 1. Log in your accounts (first run only)

Authenticates every account in `ACCOUNTS` and saves its session file so later runs don't need to log in again.

```bash
python login_accounts.py
```

### 2. Forward everything, then listen live

Backfills all existing media from `SOURCE` to `TARGET`, tracking progress via a checkpoint file, then keeps listening for new messages. If an account gets flood-waited, it automatically switches to the next account in the pool and picks up where it left off.

after Successful login Run :-
```bash
python AccountSwitch_Media_Forwarder.py
```
### 3. If forwarding speed is high by await asyncio.sleep(0) then it will fill only what's missing in group

Scans `TARGET` first to see what media already exists there, then scans `SOURCE` and forwards only the media that's missing — useful when a target channel was partially populated already and you don't want duplicates.

```bash
python SmartFill_Forwarder.py
```

### 4. Simple single-account forwarding

For smaller, one-off jobs where account rotation isn't needed. in v1.0.0

```bash
python OneClick_Media_Forward.py 
```

## How it works

- **Checkpointing**: `AccountSwitch_Media_Forwarder.py` saves the last successfully forwarded message ID to `checkpoint.json` after every message (and after every account switch), so an interrupted run resumes exactly where it stopped.
- **Duplicate prevention**: every forwarded message ID is appended to `forwarded_ids.txt`; all scripts consult this file before sending, so the same message is never forwarded twice.
- **Album grouping**: messages that share a `grouped_id` (Telegram's way of marking an album) are buffered and sent together as a single album instead of as separate messages.
- **Flood-wait rotation**: when Telegram raises `FloodWaitError`, the current account is marked as cooling down for that many seconds, and the next account in `ACCOUNTS` takes over. If every account is flood-waited, the script waits for whichever one recovers soonest.

## Troubleshooting

- **"ERROR finding source/target"** — double-check the identifier in `config.py`; make sure the logged-in account is a member of that chat, and that usernames include no leading `@` inconsistencies.
- **Repeated FloodWait on all accounts** — add more accounts to the pool, or increase the delay between sends in the script (`asyncio.sleep(...)` calls).
- **Nothing forwards on resume** — delete `checkpoint.json` only if you intentionally want to re-scan from the beginning; otherwise leave it in place so progress isn't lost.

## Contributing

Contributions are welcome!

1. Fork the repo and create a branch for your change.
2. Keep changes focused — one feature or fix per pull request.
3. Test your changes against a real (test) Telegram chat before submitting.
4. Open a pull request describing what changed and why.

Bug reports and feature requests are welcome via GitHub Issues.

## Disclaimer

This project is for educational and personal use. You are responsible for complying with [Telegram's Terms of Service](https://telegram.org/tos) and applicable law, including respecting copyright and the privacy of chat members, when forwarding content.

## License

[MIT](LICENSE)
