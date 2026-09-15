from telethon import TelegramClient, events
from telethon.errors import FloodWaitError, WorkerBusyTooLongRetryError
from telethon.tl.types import MessageMediaWebPage
from config import ACCOUNTS, SOURCE, TARGET, BASE_DIR
import asyncio
import json
import os
import time

RETRY_LIMIT = 3
RETRY_DELAY = 5

CHECKPOINT_FILE = os.path.join(BASE_DIR, "checkpoint.json")
LOG_FILE = os.path.join(BASE_DIR, "forwarded_ids.txt")

# ============================================================
#                     DO NOT EDIT BELOW
# ============================================================

def load_forwarded_ids():
    if not os.path.exists(LOG_FILE):
        return set()
    with open(LOG_FILE, "r") as f:
        return set(int(line.strip()) for line in f if line.strip().isdigit())


def log_forwarded_id(msg_id):
    with open(LOG_FILE, "a") as f:
        f.write(f"{msg_id}\n")


def log_forwarded_ids_bulk(msg_ids):
    with open(LOG_FILE, "a") as f:
        for mid in msg_ids:
            f.write(f"{mid}\n")


def save_checkpoint(last_forwarded_id):
    with open(CHECKPOINT_FILE, "w") as f:
        json.dump({"last_forwarded_id": last_forwarded_id}, f)


def load_checkpoint():
    checkpoint_id = 0
    if os.path.exists(CHECKPOINT_FILE):
        with open(CHECKPOINT_FILE, "r") as f:
            checkpoint_id = json.load(f).get("last_forwarded_id", 0)

    log_max = 0
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, "r") as f:
            for line in f:
                stripped = line.strip()
                if stripped.isdigit():
                    val = int(stripped)
                    if val > log_max:
                        log_max = val

    return max(checkpoint_id, log_max)


async def send_album(client, target, messages):
    files = [msg.media for msg in messages if msg.media]
    caption = ""
    for msg in messages:
        if msg.text:
            caption = msg.text
            break
    if not files:
        return
    for attempt in range(1, RETRY_LIMIT + 1):
        try:
            await client.send_file(target, files, caption=caption)
            return
        except WorkerBusyTooLongRetryError:
            print(f"    Telegram busy, retry {attempt}/{RETRY_LIMIT} in {RETRY_DELAY}s...")
            await asyncio.sleep(RETRY_DELAY)
    await client.send_file(target, files, caption=caption)


async def send_single(client, target, message):
    if message.media:
        for attempt in range(1, RETRY_LIMIT + 1):
            try:
                await client.send_file(target, message.media, caption=message.text or "")
                return
            except WorkerBusyTooLongRetryError:
                print(f"    Telegram busy, retry {attempt}/{RETRY_LIMIT} in {RETRY_DELAY}s...")
                await asyncio.sleep(RETRY_DELAY)
        await client.send_file(target, message.media, caption=message.text or "")
    elif message.text:
        await client.send_message(target, message.text)


async def forward_with_account(account_cfg, resume_from_id, forwarded_ids):
    """
    Forward all messages from SOURCE using this account, starting after resume_from_id.
    Albums (grouped media) are sent as a single album, not individual files.
    Returns (last_id, hit_flood, flood_seconds).
    """
    print(f"\n  Connecting: {account_cfg['name']}...")
    client = TelegramClient(account_cfg["session"], account_cfg["api_id"], account_cfg["api_hash"])
    await client.start()

    print(f"\n{'='*55}")
    print(f"  ACTIVE: {account_cfg['name']}")
    print(f"  Resuming after message ID {resume_from_id}")
    print(f"{'='*55}")

    await client.get_dialogs(limit=None)

    try:
        source = await client.get_entity(SOURCE)
    except Exception as e:
        print(f"  ERROR finding source: {e}")
        await client.disconnect()
        return resume_from_id, False, 0

    try:
        target = await client.get_entity(TARGET)
    except Exception as e:
        print(f"  ERROR finding target: {e}")
        await client.disconnect()
        return resume_from_id, False, 0

    last_id = resume_from_id
    count = 0
    hit_flood = False
    flood_seconds = 0

    pending_album_id = None
    pending_album_msgs = []

    async for message in client.iter_messages(source, min_id=resume_from_id, reverse=True):
        if message.id in forwarded_ids:
            continue
        if not message.media and not message.text:
            continue
        if isinstance(message.media, MessageMediaWebPage):
            continue

        # --- Album grouping logic ---
        if message.grouped_id:
            if pending_album_id == message.grouped_id:
                pending_album_msgs.append(message)
                continue
            else:
                # New album started — flush the previous one first
                if pending_album_msgs:
                    try:
                        ids = [m.id for m in pending_album_msgs]
                        print(f"  [{account_cfg['name']}] Forwarding album ({len(pending_album_msgs)} items) IDs {ids[0]}-{ids[-1]}")
                        await send_album(client, target, pending_album_msgs)
                        log_forwarded_ids_bulk(ids)
                        forwarded_ids.update(ids)
                        last_id = ids[-1]
                        count += len(pending_album_msgs)
                        save_checkpoint(last_id)
                        await asyncio.sleep(2)
                    except FloodWaitError as e:
                        flood_seconds = e.seconds
                        print(f"\n  [{account_cfg['name']}] FLOODWAIT {e.seconds}s at album IDs {ids[0]}-{ids[-1]}")
                        save_checkpoint(last_id)
                        hit_flood = True
                        break
                    except Exception as e:
                        print(f"  [{account_cfg['name']}] ERROR on album: {e}")

                pending_album_id = message.grouped_id
                pending_album_msgs = [message]
                continue
        else:
            # Non-album message — flush any pending album first
            if pending_album_msgs:
                try:
                    ids = [m.id for m in pending_album_msgs]
                    print(f"  [{account_cfg['name']}] Forwarding album ({len(pending_album_msgs)} items) IDs {ids[0]}-{ids[-1]}")
                    await send_album(client, target, pending_album_msgs)
                    log_forwarded_ids_bulk(ids)
                    forwarded_ids.update(ids)
                    last_id = ids[-1]
                    count += len(pending_album_msgs)
                    save_checkpoint(last_id)
                    await asyncio.sleep(2)
                except FloodWaitError as e:
                    flood_seconds = e.seconds
                    print(f"\n  [{account_cfg['name']}] FLOODWAIT {e.seconds}s at album IDs {ids[0]}-{ids[-1]}")
                    save_checkpoint(last_id)
                    hit_flood = True
                    break
                except Exception as e:
                    print(f"  [{account_cfg['name']}] ERROR on album: {e}")
                pending_album_id = None
                pending_album_msgs = []

            if hit_flood:
                break

            # Send the single message
            if not message.media:
                continue

            try:
                print(f"  [{account_cfg['name']}] Forwarding msg ID {message.id}")
                await send_single(client, target, message)
                log_forwarded_id(message.id)
                forwarded_ids.add(message.id)
                last_id = message.id
                count += 1
                save_checkpoint(last_id)

                if count % 25 == 0:
                    print(f"  [{account_cfg['name']}] --- {count} forwarded so far ---")

                await asyncio.sleep(2)

            except FloodWaitError as e:
                flood_seconds = e.seconds
                print(f"\n  [{account_cfg['name']}] FLOODWAIT {e.seconds}s at msg ID {last_id}")
                print(f"  [{account_cfg['name']}] Forwarded {count} messages this round")
                save_checkpoint(last_id)
                hit_flood = True
                break

            except Exception as e:
                print(f"  [{account_cfg['name']}] ERROR on msg {message.id}: {e}")

    # Flush any remaining album at the end
    if pending_album_msgs and not hit_flood:
        try:
            ids = [m.id for m in pending_album_msgs]
            print(f"  [{account_cfg['name']}] Forwarding album ({len(pending_album_msgs)} items) IDs {ids[0]}-{ids[-1]}")
            await send_album(client, target, pending_album_msgs)
            log_forwarded_ids_bulk(ids)
            forwarded_ids.update(ids)
            last_id = ids[-1]
            count += len(pending_album_msgs)
            save_checkpoint(last_id)
        except FloodWaitError as e:
            flood_seconds = e.seconds
            save_checkpoint(last_id)
            hit_flood = True
        except Exception as e:
            print(f"  [{account_cfg['name']}] ERROR on final album: {e}")

    if not hit_flood:
        print(f"\n  [{account_cfg['name']}] DONE - forwarded {count} messages total")

    await client.disconnect()
    return last_id, hit_flood, flood_seconds


async def listen_for_new(forwarded_ids):
    """After all old messages are forwarded, listen for new ones."""
    acc = ACCOUNTS[0]
    client = TelegramClient(acc["session"], acc["api_id"], acc["api_hash"])
    await client.start()

    await client.get_dialogs(limit=None)
    source = await client.get_entity(SOURCE)
    target = await client.get_entity(TARGET)

    print(f"\n  [{acc['name']}] Listening for new messages...")

    album_buffer = {}
    album_timers = {}

    @client.on(events.NewMessage(chats=source))
    async def handler(event):
        if not event.media:
            return

        fwd_ids = load_forwarded_ids()
        if event.id in fwd_ids:
            return

        if event.message.grouped_id:
            gid = event.message.grouped_id
            if gid not in album_buffer:
                album_buffer[gid] = []
            album_buffer[gid].append(event.message)

            if gid in album_timers:
                album_timers[gid].cancel()

            async def flush_album(group_id):
                await asyncio.sleep(1.5)
                msgs = album_buffer.pop(group_id, [])
                album_timers.pop(group_id, None)
                if not msgs:
                    return
                try:
                    ids = [m.id for m in msgs]
                    print(f"  [LIVE] Forwarding album ({len(msgs)} items) IDs {ids[0]}-{ids[-1]}")
                    await send_album(client, target, msgs)
                    log_forwarded_ids_bulk(ids)
                except FloodWaitError as e:
                    print(f"  [LIVE] FloodWait {e.seconds}s — waiting...")
                    await asyncio.sleep(e.seconds)
                except Exception as e:
                    print(f"  [LIVE] Album ERROR: {e}")

            album_timers[gid] = asyncio.ensure_future(flush_album(gid))
        else:
            try:
                print(f"  [LIVE] Forwarding msg ID {event.id}")
                await send_single(client, target, event.message)
                log_forwarded_id(event.id)
            except FloodWaitError as e:
                print(f"  [LIVE] FloodWait {e.seconds}s — waiting...")
                await asyncio.sleep(e.seconds)
            except Exception as e:
                print(f"  [LIVE] ERROR: {e}")

    await client.run_until_disconnected()


async def run():
    forwarded_ids = load_forwarded_ids()
    resume_from_id = load_checkpoint()

    print(f"Checkpoint: resume after msg ID {resume_from_id}")
    print(f"Already forwarded: {len(forwarded_ids)} messages")
    print(f"Account pool: {len(ACCOUNTS)} accounts")

    account_index = 0
    flood_wait_tracker = {}

    while True:
        acc = ACCOUNTS[account_index]

        if len(flood_wait_tracker) >= len(ACCOUNTS):
            shortest_name = min(flood_wait_tracker, key=flood_wait_tracker.get)
            wait_time = max(flood_wait_tracker[shortest_name] - time.time(), 10)
            print(f"\n  All {len(ACCOUNTS)} accounts are flood-waited.")
            print(f"  Waiting {int(wait_time)}s for {shortest_name} to cool down...")
            await asyncio.sleep(wait_time)
            flood_wait_tracker.clear()
            continue

        if acc["name"] in flood_wait_tracker and time.time() < flood_wait_tracker[acc["name"]]:
            remaining = int(flood_wait_tracker[acc["name"]] - time.time())
            print(f"\n  {acc['name']} still flood-waited ({remaining}s left), skipping...")
            account_index = (account_index + 1) % len(ACCOUNTS)
            continue

        flood_wait_tracker.pop(acc["name"], None)

        last_id, hit_flood, flood_seconds = await forward_with_account(acc, resume_from_id, forwarded_ids)

        if hit_flood:
            resume_from_id = last_id
            flood_wait_tracker[acc["name"]] = time.time() + flood_seconds
            next_index = (account_index + 1) % len(ACCOUNTS)

            print(f"\n  >>> SWITCHING: {acc['name']} -> {ACCOUNTS[next_index]['name']}")
            print(f"  >>> Checkpoint: msg ID {resume_from_id}")

            account_index = next_index
            await asyncio.sleep(2)
        else:
            break

    print("\n" + "=" * 55)
    print("  ALL MESSAGES FORWARDED!")
    print("=" * 55)

    await listen_for_new(forwarded_ids)


if __name__ == "__main__":
    while True:
        try:
            asyncio.run(run())
        except KeyboardInterrupt:
            print("\nStopped by user.")
            break
        except Exception as e:
            print(f"Crashed: {e}. Reconnecting in 10s...")
            time.sleep(10)
