import time
import re
import os
import json
import random
import logging
from rcon.source import Client

# Configuration via Environment Variables
RCON_HOST = os.getenv('RCON_HOST', '192.168.1.50')
RCON_PORT = int(os.getenv('RCON_PORT', '27015'))
RCON_PASS = os.getenv('RCON_PASS', 'password')
MAP_DURATION = int(os.getenv('MAP_DURATION', '60'))    # minutes each map runs
GRACE_PERIOD = int(os.getenv('GRACE_PERIOD', '15'))    # extra minutes before a forced changelevel
POLL_INTERVAL = int(os.getenv('POLL_INTERVAL', '30'))  # seconds between status polls

MAPS_FILE = os.path.join(os.path.dirname(__file__), 'data', 'maps.json')

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


def load_t1_maps(maps_file):
    """Load maps.json and return a list of map keys that are Tier 1."""
    with open(maps_file, 'r') as f:
        maps = json.load(f)

    t1_maps = []
    for key, data in maps.items():
        display = data.get('display', '')
        match = re.search(r'T(\d+)', display)
        if match and match.group(1) == '1':
            t1_maps.append(key)

    return t1_maps


def get_current_map(client):
    """
    Run 'status' via RCON and parse the active map name from the spawngroup line.
    Returns the map name string (e.g. 'surf_oasis') or None if unparseable.
    """
    response = client.run('status')
    match = re.search(r'\[1:\s+(surf_\S+?)\s*\|', response)
    if match:
        return match.group(1)
    logging.warning(f"Could not parse map name from status: {repr(response[:300])}")
    return None


def send_say(client, message):
    """Send a chat message to all players via RCON."""
    client.run(f'say [Server] {message}')
    logging.info(f"[say] {message}")


def trigger_vote(client):
    """Kick off a ggmc map vote."""
    client.run('ggmc_mapvote_start 25')
    logging.info("Triggered ggmc_mapvote_start 25")


def force_changelevel(client, map_name):
    """Force a map change via RCON."""
    response = client.run(f'ds_workshop_changelevel {map_name}')
    logging.info(f"force_changelevel to {map_name}: {repr(response)}")


def pick_random_t1_map(t1_maps, exclude_map):
    """Pick a random T1 map, excluding exclude_map."""
    pool = [m for m in t1_maps if m != exclude_map]
    if not pool:
        pool = t1_maps  # fallback in case the entire pool is just one map
    return random.choice(pool)


def main():
    t1_maps = load_t1_maps(MAPS_FILE)
    logging.info(f"Map auto-rotate started. T1 pool: {len(t1_maps)} maps")
    logging.info(f"T1 maps: {t1_maps}")
    logging.info(
        f"Config: RCON={RCON_HOST}:{RCON_PORT}, MAP_DURATION={MAP_DURATION}m, "
        f"GRACE_PERIOD={GRACE_PERIOD}m, POLL_INTERVAL={POLL_INTERVAL}s"
    )

    last_map = None           # last confirmed active map name
    map_end_time = None       # time.time() when the current map's internal timer expires
    vote_triggered = False    # whether ggmc_mapvote_start was issued this cycle
    grace_start_time = None   # time.time() when the grace period started (None = not in grace)
    last_announced_mark = -1  # last 5-min mark (in minutes) that was sent via say
    history = []              # in-memory list of maps played this session

    while True:
        try:
            with Client(RCON_HOST, RCON_PORT, passwd=RCON_PASS, timeout=10) as client:
                current_map = get_current_map(client)

            if current_map is None:
                logging.warning("Could not detect current map — retrying in %ds.", POLL_INTERVAL)
                time.sleep(POLL_INTERVAL)
                continue

            now = time.time()

            # ------------------------------------------------------------------
            # New map detected (first run or the map changed)
            # ------------------------------------------------------------------
            if (last_map is None) or (current_map != last_map):
                logging.info(f"New map detected: {current_map!r} (previous: {last_map!r})")
                history.append(current_map)
                last_map = current_map
                map_end_time = now + MAP_DURATION * 60
                vote_triggered = False
                grace_start_time = None
                last_announced_mark = MAP_DURATION  # skip redundant "N min remaining" at full time

                with Client(RCON_HOST, RCON_PORT, passwd=RCON_PASS, timeout=10) as client:
                    send_say(
                        client,
                        f"Welcome to {current_map}! This map will run for {MAP_DURATION} minutes.",
                    )

                time.sleep(POLL_INTERVAL)
                continue

            # ------------------------------------------------------------------
            # Grace period: timer expired but the map hasn't changed yet
            # ------------------------------------------------------------------
            if grace_start_time is not None:
                grace_elapsed = now - grace_start_time
                grace_remaining_secs = max(0.0, GRACE_PERIOD * 60 - grace_elapsed)
                grace_remaining_min = int(grace_remaining_secs / 60)

                # Every-5-min warnings while in grace period
                grace_mark = (grace_remaining_min // 5) * 5
                if grace_mark > 0 and grace_mark != last_announced_mark:
                    with Client(RCON_HOST, RCON_PORT, passwd=RCON_PASS, timeout=10) as client:
                        send_say(
                            client,
                            f"Map vote completed but the map hasn't changed yet. "
                            f"Forcing a change in {grace_mark} minute{'s' if grace_mark != 1 else ''}.",
                        )
                    last_announced_mark = grace_mark

                if grace_elapsed >= GRACE_PERIOD * 60:
                    forced_map = pick_random_t1_map(t1_maps, last_map)
                    logging.info(f"Grace period expired — forcing map change to {forced_map}.")
                    with Client(RCON_HOST, RCON_PORT, passwd=RCON_PASS, timeout=10) as client:
                        send_say(client, f"Forcing map change to {forced_map}! See you there!")
                        force_changelevel(client, forced_map)
                    # Reset state and wait for the server to load the new map
                    last_map = None
                    map_end_time = None
                    vote_triggered = False
                    grace_start_time = None
                    last_announced_mark = -1
                    logging.info("Waiting 90s for server to load forced map...")
                    time.sleep(90)

                time.sleep(POLL_INTERVAL)
                continue

            # ------------------------------------------------------------------
            # Normal timer: countdown announcements, vote trigger, and expiry
            # ------------------------------------------------------------------
            seconds_remaining = map_end_time - now
            minutes_remaining = int(seconds_remaining / 60)
            logging.info(
                f"Map: {current_map} | ~{minutes_remaining}m {int(seconds_remaining % 60)}s remaining"
            )

            if seconds_remaining <= 0:
                if not vote_triggered:
                    # Edge case: somehow missed the 1-min trigger — fire vote immediately
                    logging.warning("Timer expired without a vote trigger — firing vote now.")
                    with Client(RCON_HOST, RCON_PORT, passwd=RCON_PASS, timeout=10) as client:
                        send_say(client, "Time is up! Starting a map vote now...")
                        trigger_vote(client)
                    vote_triggered = True
                else:
                    # Vote was already triggered; move into the grace period
                    logging.info("Timer expired after vote. Entering grace period.")
                    grace_start_time = now
                    last_announced_mark = -1
                    with Client(RCON_HOST, RCON_PORT, passwd=RCON_PASS, timeout=10) as client:
                        send_say(client, "Vote has concluded — waiting for the map to change...")

            elif seconds_remaining <= 60 and not vote_triggered:
                # 1-minute warning + trigger the vote
                with Client(RCON_HOST, RCON_PORT, passwd=RCON_PASS, timeout=10) as client:
                    send_say(client, "1 minute left! Starting a map vote now...")
                    trigger_vote(client)
                vote_triggered = True

            elif minutes_remaining > 1 and minutes_remaining % 5 == 0 and minutes_remaining != last_announced_mark:
                # Regular 5-minute countdown announcement
                with Client(RCON_HOST, RCON_PORT, passwd=RCON_PASS, timeout=10) as client:
                    send_say(client, f"{minutes_remaining} minutes remaining on this map.")
                last_announced_mark = minutes_remaining

        except Exception as e:
            logging.error(f"Unhandled error in main loop: {e}")

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()