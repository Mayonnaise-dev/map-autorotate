# Map Auto-Rotate

A Docker-based map rotation service for Counter-Strike 2 surf servers. Tracks an internal per-map timer via RCON and automatically triggers GGMC map votes or forces a random Tier 1 map change when time runs out.

## Features

- ⏱️ Internal per-map timer with configurable duration (default 60 minutes)
- 🗳️ Triggers a GGMC map vote (`ggmc_mapvote_start`) with 1 minute remaining
- 🗺️ Falls back to a random Tier 1 map if the server is empty or the vote doesn't result in a map change
- 📢 In-game countdown announcements every 5 minutes with alternating `!nominate` reminders
- 🔍 Detects manual or external map changes and resets the timer automatically
- 🚫 Never picks the same map back-to-back for forced changes
- ⏳ Configurable grace period after a vote before forcing a map change
- 🐳 Dockerized for easy deployment
- ⚙️ Fully configurable via environment variables

## How It Works

1. On startup, `data/maps.json` is loaded and all Tier 1 maps are extracted into the rotation pool.
2. The script polls the server's `status` via RCON every `POLL_INTERVAL` seconds (default 30) to detect the current map.
3. When a new map is detected, an internal timer is started for `MAP_DURATION` minutes (default 60) and a welcome message is sent in chat.
4. Every 5 minutes, a countdown announcement is sent to players (alternating with a `!nominate` reminder).
5. With 1 minute remaining:
   - If no players are connected, the vote is skipped and a random T1 map is forced via `ds_workshop_changelevel`.
   - If players are connected, a GGMC map vote is triggered (`ggmc_mapvote_start 25`).
6. 1 minute after the vote starts, `ggmc_change_nextmap` is executed to apply the vote result.
7. A grace period begins (`GRACE_PERIOD` minutes, default 15). If the map still hasn't changed after the grace period expires, a random T1 map is forced.
8. If a manual map change is detected at any point (the map name changes unexpectedly), the timer resets for the new map.

## Quick Start

1. **Clone the repository**
   ```bash
   git clone <repo-url>
   cd map-autorotate
   ```

2. **Configure environment**

   Create a `.env` file with your server details (see [Configuration](#configuration) below).

3. **Add your maps**

   Edit `data/maps.json`. Each entry needs a `display` field containing the tier in the format `T<n>` (e.g. `T1`, `T2`). Only maps marked `T1` are included in the rotation pool.

   ```json
   {
       "surf_mesa_revo": {
           "ws": true,
           "display": "Mesa_revo - Linear T1",
           "mapid": "3076980482"
       }
   }
   ```

4. **Deploy with Docker**
   ```bash
   docker-compose up -d
   ```

## Configuration

Set the following environment variables in your `.env` file:

| Variable | Description | Default |
|----------|-------------|---------|
| `RCON_HOST` | CS2 server IP address | `192.168.1.50` |
| `RCON_PORT` | RCON port | `27015` |
| `RCON_PASS` | RCON password | `password` |
| `MAP_DURATION` | Minutes each map runs before a vote is triggered | `60` |
| `GRACE_PERIOD` | Minutes to wait after a vote before forcing a map change | `15` |
| `POLL_INTERVAL` | Seconds between RCON status polls | `30` |

## Requirements

- Docker & Docker Compose
- CS2 server with RCON enabled
- [GGMC](https://github.com/ssypchenko/cs2-gganbu-mapchooser) plugin installed on the server (for map votes)

## License

MIT License - see LICENSE file for details.
