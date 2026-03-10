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
    Pre-flight check then issue changelevel.
    Returns the new map name if changed, or None if aborted (manual change detected).
    """
    logging.info("Performing pre-flight timeleft check before map change...")
    try:
        with Client(RCON_HOST, RCON_PORT, passwd=RCON_PASS, timeout=10) as client:
            seconds_left = get_timeleft(client)

        if seconds_left is not None and seconds_left > MANUAL_CHANGE_THRESHOLD:
            logging.warning(
                f"Pre-flight: timeleft is {seconds_left}s — manual map change detected. Aborting."
            )
            return None

        next_map = pick_next_map(t1_maps, last_map)
        logging.info(f"Changing map to: {next_map}")

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

    expected_end = None  # timestamp (time.time()) when current map should end
    last_map = None      # last map that was changed to (in-memory only)

    while True:
        try:
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
                # First iteration — establish the baseline
                expected_end = now + seconds_left

            # Time is up — change map immediately
            if seconds_left == 0:
                logging.info("Timeleft is 0 — triggering map change now.")
                new_map = do_map_change(t1_maps, last_map)
                if new_map:
                    last_map = new_map
                    expected_end = None  # will be re-established on next poll
                    logging.info(f"Map changed to {new_map}. Waiting 60s for server to load...")
                    time.sleep(60)
                else:
                    # Aborted — re-sync timer on next poll
                    expected_end = None
                continue

            # Map ends before next regular check — sleep until just after it expires
            if seconds_left <= CHECK_INTERVAL:
                sleep_for = seconds_left + 5
                logging.info(f"Map ends in {seconds_left}s — sleeping {sleep_for}s then changing map.")
                time.sleep(sleep_for)

                new_map = do_map_change(t1_maps, last_map)
                if new_map:
                    last_map = new_map
                    expected_end = None
                    logging.info(f"Map changed to {new_map}. Waiting 60s for server to load...")
                    time.sleep(60)
                else:
                    expected_end = None
                continue

            # Plenty of time left — wait for next check
            time.sleep(CHECK_INTERVAL)

        except Exception as e:
            logging.error(f"RCON error: {e}")
            time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()