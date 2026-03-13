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
POLL_INTERVAL = 300        # seconds between regular player-count polls (5 minutes)
FINAL_CHECK_INTERVAL = 60  # seconds before the last safety check before changing map

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
    logging.info(f"Polling every {POLL_INTERVAL}s for player count.")

    last_map = None
    consecutive_empty = 0  # number of consecutive 5-minute polls with no players

    while True:
        try:
            # --- Regular poll: check for players ---
            with Client(RCON_HOST, RCON_PORT, passwd=RCON_PASS, timeout=10) as client:
                players_online = has_players(client)

            if players_online:
                if consecutive_empty > 0:
                    logging.info("Players detected — resetting empty counter.")
                consecutive_empty = 0
                time.sleep(POLL_INTERVAL)
                continue

            # No players this poll
            consecutive_empty += 1
            logging.info(f"Server empty (consecutive empty polls: {consecutive_empty}).")

            if consecutive_empty == 1:
                # First empty poll — wait another 5 minutes before acting
                logging.info("Will check again in 5 minutes before taking action.")
                time.sleep(POLL_INTERVAL)
                continue

            # Second consecutive empty poll — check map time
            with Client(RCON_HOST, RCON_PORT, passwd=RCON_PASS, timeout=10) as client:
                seconds_left = get_timeleft(client)

            if seconds_left is None:
                logging.warning("Could not read map time — resetting and retrying next poll.")
                consecutive_empty = 0
                time.sleep(POLL_INTERVAL)
                continue

            if seconds_left > 0:
                logging.info(
                    f"Server empty but map still has {seconds_left // 60}m {seconds_left % 60}s "
                    f"remaining — resetting and waiting."
                )
                consecutive_empty = 0
                time.sleep(POLL_INTERVAL)
                continue

            # Map time is 0 — one final safety check 1 minute from now
            logging.info("Map time is 0 and server is empty — final safety check in 1 minute.")
            time.sleep(FINAL_CHECK_INTERVAL)

            with Client(RCON_HOST, RCON_PORT, passwd=RCON_PASS, timeout=10) as client:
                players_online = has_players(client)

            if players_online:
                logging.info("Players joined during final check — aborting map change.")
                consecutive_empty = 0
                time.sleep(POLL_INTERVAL)
                continue

            # All clear — change the map
            new_map = do_map_change(t1_maps, last_map)
            if new_map:
                last_map = new_map
                logging.info(f"Map changed to {new_map}. Waiting 60s for server to load...")
                time.sleep(60)
            consecutive_empty = 0
            time.sleep(POLL_INTERVAL)

        except Exception as e:
            logging.error(f"RCON error: {e}")
            time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()