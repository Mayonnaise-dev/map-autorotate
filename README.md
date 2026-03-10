# Map Auto-Rotate

A Docker-based map rotation service for Counter-Strike 2 surf servers. Polls the server's `timeleft` via RCON every 60 seconds and automatically changes to a randomly selected Tier 1 map when the current map timer expires.

## Features

- ⏱️ Polls `timeleft` every 60 seconds via RCON
- 🗺️ Randomly selects the next map from a configurable Tier 1 map pool
- 🔍 Detects manual map changes mid-rotation and resyncs the timer
- 🚫 Never repeats the same map back-to-back
- 🐳 Dockerized for easy deployment
- ⚙️ Configurable via environment variables

## How It Works

1. On startup, `data/maps.json` is loaded and all Tier 1 maps are extracted into the rotation pool.
2. Every 60 seconds the service queries `timeleft` via RCON and tracks when the current map should end.
3. If a manual map change is detected (timeleft jumps significantly), the internal timer is reset.
4. When the map is about to expire, a pre-flight `timeleft` check confirms the timing, then `changelevel <map>` is issued to a randomly chosen T1 map.

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

## Requirements

- Docker & Docker Compose
- CS2 server with RCON enabled
- `timeleft` command available on the server (e.g. via SharpTimer)

## License

MIT License - see LICENSE file for details.
