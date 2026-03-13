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
CHECK_INTERVAL = 60  # seconds between timeleft polls
MANUAL_CHANGE_THRESHOLD = 90  # if timeleft jumps by more than this, treat as manual change

MAPS_FILE = os.path.join(os.path.dirname(__file__), 'data', 'maps.json')
PLAYER_CHECK_INTERVAL = 60  # seconds between player-count polls when waiting for empty server

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


def get_timeleft(client):
    """
    Run 'timeleft' via RCON and return remaining seconds, or None if unparseable.
    Prints the raw response for debugging.
    """
    response = client.run('timeleft')
    print(f"[DEBUG] timeleft raw response: {repr(response)}")

    match = re.search(r'Time Remaining:\s+(\d+):(\d+)', response)
    if match:
        minutes = int(match.group(1))
        seconds = int(match.group(2))
        return minutes * 60 + seconds

    logging.warning(f"Could not parse timeleft from response: {repr(response)}")
    return None


def parse_status(status_output):
    """
    Parses CS2 'status' command output.
    Returns a list of dicts: {'userid': '12', 'name': 'Player', 'ip': '1.2.3.4'}
    Skips bots and connecting players (userid 65535).
    """
    players = []
    lines = status_output.split('\n')
    in_player_section = False

    for line in lines:
        if '---------players--------' in line:
            in_player_section = True
            continue

        if in_player_section and ('#end' in line or line.strip() == ''):
            break

        if in_player_section and line.strip():
            if 'id     time ping loss' in line:
                continue

            try:
                if 'BOT' in line:
                    continue

                if line.strip().startswith('65535'):
                    continue

                parts = line.split()

                ip_port = None
                for part in parts:
                    if ':' in part and '.' in part:
                        ip_port = part
                        break

                if ip_port:
                    ip = ip_port.split(':')[0]
                    name_match = re.search(r"'(.*?)'", line)
                    name = name_match.group(1) if name_match else 'Unknown'
                    players.append({'userid': parts[0], 'name': name, 'ip': ip})

            except Exception as e:
                logging.warning(f"Failed to parse status line: {line!r} - {e}")

    return players


def has_players(client):
    """Returns True if there are real players on the server, False if empty."""
    response = client.run('status')
    players = parse_status(response)
    count = len(players)
    if count > 0:
        logging.info(f"{count} player(s) online — waiting for server to empty.")
    else:
        logging.info("Server is empty.")
    return count > 0


def change_map(client, map_name):
    """Issue the changelevel command via RCON."""
    response = client.run(f'ds_workshop_changelevel {map_name}')
    logging.info(f"changelevel response: {repr(response)}")


def pick_next_map(t1_maps, last_map):
    """Pick a random T1 map, excluding the last played map."""
    pool = [m for m in t1_maps if m != last_map]
    if not pool:
        pool = t1_maps  # fallback: only one map in pool
    return random.choice(pool)


def do_map_change(t1_maps, last_map):
    """
    Pick a random T1 map and issue changelevel.
    Returns the new map name, or None on RCON error.
    """
    next_map = pick_next_map(t1_maps, last_map)
    logging.info(f"Changing map to: {next_map}")
    try:
        with Client(RCON_HOST, RCON_PORT, passwd=RCON_PASS, timeout=10) as client:
            change_map(client, next_map)
        return next_map
    except Exception as e:
        logging.error(f"RCON error during map change: {e}")
        return None


def main():
    t1_maps = load_t1_maps(MAPS_FILE)
    logging.info(f"Map auto-rotate started. T1 pool: {len(t1_maps)} maps")
    logging.info(f"T1 maps: {t1_maps}")
    logging.info(f"Configuration: RCON_HOST={RCON_HOST}, RCON_PORT={RCON_PORT}")

    expected_end = None   # timestamp (time.time()) when current map should end
    last_map = None       # last map that was changed to (in-memory only)
    waiting_for_empty = False  # True when the timer has expired and we need the server to empty

    while True:
        try:
            # ----------------------------------------------------------------
            # WAITING_FOR_EMPTY state
            # The map timer has expired. Poll every PLAYER_CHECK_INTERVAL until
            # no real players remain, then issue changelevel.
            # ----------------------------------------------------------------
            if waiting_for_empty:
                with Client(RCON_HOST, RCON_PORT, passwd=RCON_PASS, timeout=10) as client:
                    # Guard: if timeleft jumped someone changed the map manually
                    seconds_left = get_timeleft(client)
                    if seconds_left is not None and seconds_left > MANUAL_CHANGE_THRESHOLD:
                        logging.warning(
                            f"Manual map change detected while waiting for empty server "
                            f"(timeleft={seconds_left}s). Resuming monitoring."
                        )
                        waiting_for_empty = False
                        expected_end = time.time() + seconds_left
                        time.sleep(CHECK_INTERVAL)
                        continue

                    server_empty = not has_players(client)

                if server_empty:
                    new_map = do_map_change(t1_maps, last_map)
                    if new_map:
                        last_map = new_map
                        logging.info(f"Map changed to {new_map}. Waiting 60s for server to load...")
                        time.sleep(60)
                    waiting_for_empty = False
                    expected_end = None
                else:
                    time.sleep(PLAYER_CHECK_INTERVAL)
                continue

            # ----------------------------------------------------------------
            # MONITORING state
            # Poll timeleft and track when the current map should end.
            # ----------------------------------------------------------------
            with Client(RCON_HOST, RCON_PORT, passwd=RCON_PASS, timeout=10) as client:
                seconds_left = get_timeleft(client)

            if seconds_left is None:
                logging.warning("Could not get timeleft, retrying in 60s.")
                time.sleep(CHECK_INTERVAL)
                continue

            now = time.time()
            logging.info(f"Time remaining on current map: {seconds_left // 60}m {seconds_left % 60}s")

            # Detect manual map change: timeleft is significantly higher than expected
            if expected_end is not None:
                expected_remaining = expected_end - now
                if seconds_left - expected_remaining > MANUAL_CHANGE_THRESHOLD:
                    logging.warning(
                        f"Manual map change detected — expected ~{int(expected_remaining)}s left, "
                        f"got {seconds_left}s. Resetting timer."
                    )
                    expected_end = now + seconds_left
                    time.sleep(CHECK_INTERVAL)
                    continue
            else:
                # First iteration or post-change — establish the baseline
                expected_end = now + seconds_left

            # Timer expired — enter waiting-for-empty state
            if seconds_left == 0:
                logging.info("Timeleft is 0 — waiting for server to empty before changing map.")
                waiting_for_empty = True
                continue

            # Map ends before the next regular check — sleep until just after it expires
            if seconds_left <= CHECK_INTERVAL:
                sleep_for = seconds_left + 5
                logging.info(
                    f"Map ends in {seconds_left}s — sleeping {sleep_for}s "
                    f"then waiting for server to empty."
                )
                time.sleep(sleep_for)
                waiting_for_empty = True
                expected_end = None
                continue

            # Plenty of time left — wait for next regular check
            time.sleep(CHECK_INTERVAL)

        except Exception as e:
            logging.error(f"RCON error: {e}")
            time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()