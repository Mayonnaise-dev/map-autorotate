# Map Auto-Rotate

A Docker-based map rotation service for Counter-Strike 2 surf servers. Polls the server's `timeleft` via RCON every 60 seconds and automatically changes to a randomly selected Tier 1 map when the current map timer expires — but only once the server is completely empty.

## Features

- ⏱️ Polls `timeleft` every 60 seconds via RCON
- 🗺️ Randomly selects the next map from a configurable Tier 1 map pool
- 👥 Only changes the map when **no players are connected**
- 🔍 Detects manual map changes mid-rotation and resyncs the timer
- 🚫 Never repeats the same map back-to-back
- 🐳 Dockerized for easy deployment
- ⚙️ Configurable via environment variables

## How It Works

The service operates as a two-state machine:

1. **MONITORING** — On startup, `data/maps.json` is loaded and all Tier 1 maps are extracted into the rotation pool. Every 60 seconds the service queries `timeleft` via RCON and tracks when the current map should end. If a manual map change is detected (timeleft jumps significantly), the internal timer is reset.

2. **WAITING_FOR_EMPTY** — When the map timer expires the service transitions into this state. Every 60 seconds it queries `status` via RCON and counts real connected players (bots and connecting players are excluded). Once the server is empty, `ds_workshop_changelevel <map>` is issued to a randomly chosen T1 map and the service returns to MONITORING. If a manual map change is detected while waiting (timeleft jumps), the wait is cancelled and the service returns to MONITORING immediately.

## Quick Start

1. **Clone the repository**
   ```bash
   git clone <repo-url>
   cd map-autorotate
   ```

2. **Configure environment**
   ```bash
   cp .env.example .env
   # Edit .env with your server details
   ```

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

Edit the `.env` file:

| Variable | Description | Default |
|----------|-------------|-------|
| `RCON_HOST` | CS2 server IP address | `192.168.1.50` |
| `RCON_PORT` | RCON port | `27015` |
| `RCON_PASS` | RCON password | `password` |

The player-count poll interval (while waiting for an empty server) is hardcoded to 60 seconds.

## Requirements

- Docker & Docker Compose
- CS2 server with RCON enabled
- `timeleft` command available on the server (e.g. via SharpTimer)

## License

MIT License - see LICENSE file for details.
