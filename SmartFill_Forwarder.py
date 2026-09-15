from telethon import TelegramClient
from telethon.errors import FloodWaitError, WorkerBusyTooLongRetryError
from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument, MessageMediaWebPage
from config import ACCOUNTS, SOURCE, TARGET, BASE_DIR
import asyncio
import os
import time

"""
Smart-fill: scans TARGET to see what's already there,
then scans SOURCE and only forwards media NOT in target.
No duplicates. Uses account-switching on FloodWait.
"""

LOG_FILE = os.path.join(BASE_DIR, "forwarded_ids.txt")
RETRY_LIMIT = 3
RETRY_DELAY = 5


def get_media_id(message):
    if isinstance(message.media, MessageMediaPhoto) and message.photo:
        return f"photo_{message.photo.id}"
    elif isinstance(message.media, MessageMediaDocument) and message.document:
        return f"doc_{message.document.id}"
    return None


def log_forwarded_id(msg_id):
    with open(LOG_FILE, "a") as f:
        f.write(f"{msg_id}\n")


def log_forwarded_ids_bulk(msg_ids):
    with open(LOG_FILE, "a") as f:
        for mid in msg_ids:
            f.write(f"{mid}\n")


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


async def scan_target(client):
    """Scan target channel and collect all media IDs already present."""
    target_entity = await client.get_entity(TARGET)
    target_media_ids = set()
    count = 0

    print(f"\n  Scanning TARGET channel for existing media...")

    async for message in client.iter_messages(target_entity):
        if not message.media:
            continue
        mid = get_media_id(message)
        if mid:
            target_media_ids.add(mid)
        count += 1
        if count % 5000 == 0:
            print(f"    Scanned {count} media in target ({len(target_media_ids)} unique)...")

    print(f"  TARGET scan done: {len(target_media_ids)} unique media found\n")
    return target_media_ids


async def smart_fill(account_cfg, target_media_ids):
    """
    Scan SOURCE, compare each media against target_media_ids,
    forward only what's missing.
    """
    print(f"\n  Connecting: {account_cfg['name']}...")
    client = TelegramClient(account_cfg["session"], account_cfg["api_id"], account_cfg["api_hash"])
    await client.start()

    print(f"\n{'='*55}")
    print(f"  SMART-FILL ACTIVE: {account_cfg['name']}")
    print(f"  Forwarding only media NOT in target...")
    print(f"{'='*55}")

    await client.get_dialogs(limit=None)

    try:
        source = await client.get_entity(SOURCE)
    except Exception as e:
        print(f"  ERROR finding source: {e}")
        await client.disconnect()
        return 0, 0, False, 0

    try:
        target = await client.get_entity(TARGET)
    except Exception as e:
        print(f"  ERROR finding target: {e}")
        await client.disconnect()
        return 0, 0, False, 0

    forwarded = 0
    already_exists = 0
    scanned = 0
    hit_flood = False
    flood_seconds = 0

    pending_album_id = None
    pending_album_msgs = []

    async for message in client.iter_messages(source, reverse=True):
        scanned += 1

        if scanned % 5000 == 0:
            print(f"  [{account_cfg['name']}] Scanned {scanned} | Exists: {already_exists} | Forwarded: {forwarded}")

        if not message.media or isinstance(message.media, MessageMediaWebPage):
            continue

        mid = get_media_id(message)
        if mid and mid in target_media_ids:
            already_exists += 1
            continue

        # --- Album grouping ---
        if message.grouped_id:
            if pending_album_id == message.grouped_id:
                pending_album_msgs.append(message)
                continue
            else:
                if pending_album_msgs:
                    # Check if ALL items in album already exist
                    album_mids = [get_media_id(m) for m in pending_album_msgs]
                    missing = [m for m, amid in zip(pending_album_msgs, album_mids) if not amid or amid not in target_media_ids]

                    if missing:
                        try:
                            ids = [m.id for m in pending_album_msgs]
                            print(f"  [{account_cfg['name']}] Forwarding missing album ({len(missing)}/{len(pending_album_msgs)} new) IDs {ids[0]}-{ids[-1]}")
                            await send_album(client, target, pending_album_msgs)
                            log_forwarded_ids_bulk(ids)
                            for m in pending_album_msgs:
                                amid = get_media_id(m)
                                if amid:
                                    target_media_ids.add(amid)
                            forwarded += len(pending_album_msgs)
                            await asyncio.sleep(2)
                        except FloodWaitError as e:
                            flood_seconds = e.seconds
                            print(f"\n  [{account_cfg['name']}] FLOODWAIT {e.seconds}s")
                            hit_flood = True
                            break
                        except Exception as e:
                            print(f"  [{account_cfg['name']}] Album ERROR: {e}")
                    else:
                        already_exists += len(pending_album_msgs)

                pending_album_id = message.grouped_id
                pending_album_msgs = [message]
                continue
        else:
            if pending_album_msgs:
                album_mids = [get_media_id(m) for m in pending_album_msgs]
                missing = [m for m, amid in zip(pending_album_msgs, album_mids) if not amid or amid not in target_media_ids]

                if missing:
                    try:
                        ids = [m.id for m in pending_album_msgs]
                        print(f"  [{account_cfg['name']}] Forwarding missing album ({len(missing)}/{len(pending_album_msgs)} new) IDs {ids[0]}-{ids[-1]}")
                        await send_album(client, target, pending_album_msgs)
                        log_forwarded_ids_bulk(ids)
                        for m in pending_album_msgs:
                            amid = get_media_id(m)
                            if amid:
                                target_media_ids.add(amid)
                        forwarded += len(pending_album_msgs)
                        await asyncio.sleep(2)
                    except FloodWaitError as e:
                        flood_seconds = e.seconds
                        print(f"\n  [{account_cfg['name']}] FLOODWAIT {e.seconds}s")
                        hit_flood = True
                        break
                    except Exception as e:
                        print(f"  [{account_cfg['name']}] Album ERROR: {e}")
                else:
                    already_exists += len(pending_album_msgs)

                pending_album_id = None
                pending_album_msgs = []

            if hit_flood:
                break

            try:
                print(f"  [{account_cfg['name']}] Forwarding missing msg ID {message.id}")
                await send_single(client, target, message)
                log_forwarded_id(message.id)
                if mid:
                    target_media_ids.add(mid)
                forwarded += 1
                await asyncio.sleep(2)

            except FloodWaitError as e:
                flood_seconds = e.seconds
                print(f"\n  [{account_cfg['name']}] FLOODWAIT {e.seconds}s")
                hit_flood = True
                break

            except Exception as e:
                print(f"  [{account_cfg['name']}] ERROR on msg {message.id}: {e}")

    # Flush remaining album
    if pending_album_msgs and not hit_flood:
        album_mids = [get_media_id(m) for m in pending_album_msgs]
        missing = [m for m, amid in zip(pending_album_msgs, album_mids) if not amid or amid not in target_media_ids]
        if missing:
            try:
                ids = [m.id for m in pending_album_msgs]
                print(f"  [{account_cfg['name']}] Forwarding missing album ({len(missing)}/{len(pending_album_msgs)} new) IDs {ids[0]}-{ids[-1]}")
                await send_album(client, target, pending_album_msgs)
                log_forwarded_ids_bulk(ids)
                for m in pending_album_msgs:
                    amid = get_media_id(m)
                    if amid:
                        target_media_ids.add(amid)
                forwarded += len(pending_album_msgs)
            except FloodWaitError as e:
                flood_seconds = e.seconds
                hit_flood = True
            except Exception as e:
                print(f"  [{account_cfg['name']}] Final album ERROR: {e}")

    print(f"\n  [{account_cfg['name']}] Scanned {scanned} | Already in target: {already_exists} | Forwarded: {forwarded}")

    await client.disconnect()
    return forwarded, already_exists, hit_flood, flood_seconds


async def run():
    # Step 1: Scan target with first account to see what's already there
    acc = ACCOUNTS[0]
    print(f"  Connecting: {acc['name']} (for target scan)...")
    client = TelegramClient(acc["session"], acc["api_id"], acc["api_hash"])
    await client.start()
    await client.get_dialogs(limit=None)

    target_media_ids = await scan_target(client)
    await client.disconnect()

    print(f"  {len(target_media_ids)} media already in BACKUP RARE")
    print(f"  Now scanning SOURCE to find what's missing...\n")

    # Step 2: Scan source and forward missing media with account switching
    account_index = 0
    flood_wait_tracker = {}
    total_forwarded = 0
    total_exists = 0

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

        fwd, exists, hit_flood, flood_seconds = await smart_fill(acc, target_media_ids)
        total_forwarded += fwd
        total_exists += exists

        if hit_flood:
            flood_wait_tracker[acc["name"]] = time.time() + flood_seconds
            next_index = (account_index + 1) % len(ACCOUNTS)
            print(f"\n  >>> SWITCHING: {acc['name']} -> {ACCOUNTS[next_index]['name']}")
            account_index = next_index
            await asyncio.sleep(2)
        else:
            break

    print("\n" + "=" * 55)
    print(f"  SMART-FILL COMPLETE!")
    print(f"  Already in target: {total_exists}")
    print(f"  Newly forwarded:   {total_forwarded}")
    print("=" * 55)


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
