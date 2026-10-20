# Operation

*[Deutsch](de/DEPLOYMENT.md) · English*

## Requirements

* Linux host x86_64 with Docker Engine and Compose v2. Other platforms are not tested;
  openWakeWord/tflite and the images are built for linux/amd64.
* Measured usage on the development machine (8 cores, 32 GB RAM), with two cameras, vision
  at 2 fps on one camera and all local models loaded:

  | Container | RAM | CPU when idle |
  | --- | --- | --- |
  | core | ~1.5 GB | ~20 % of one core (vision + audio pipeline) |
  | postgres | ~60 MB | < 1 % |
  | go2rtc | ~20 MB | ~2 % |
  | sandbox | ~75 MB (limit 1 GB) | < 1 % |

  YOLOX needs about 320 ms per analysed image on this CPU; it only runs on motion or every
  20 s. No GPU is needed.
* Disk space: core image about 2.7 GB (incl. all models), sandbox about 220 MB, plus the
  database.
* Network: the core container must reach cameras in the LAN (network `media`, a normal
  bridge network with NAT). A bridge network is unfavourable for multicast discovery
  (WS-Discovery, mDNS); JuStAI5 therefore searches by unicast in allowed ranges
  ([DEVICES.md](DEVICES.md#adding)).

## Installation

Detailed guide for beginners (install Docker, API key, first devices):
[INSTALLATION.md](INSTALLATION.md). Automatically: `scripts/install.sh` (checks platform
and Docker, creates `.env` with LAN address, network range and free ports, starts and
waits for `/api/health`; running it again keeps `.env` and rebuilds). By hand:

```bash
git clone https://github.com/julianstricker/JuStAI5.git justai5 && cd justai5
cp .env.example .env        # optional: port, admin password, Google API key, network ranges
docker compose up -d --build
docker compose exec core cat /data/initial_admin_password.txt
```

At the first start:

1. `secrets-init` creates DB password, master key and sandbox token in the volume
   `secrets`.
2. PostgreSQL starts; the core migrates the schema (Alembic) automatically.
3. Bundled plugins are registered and enabled with `default_enabled`.
4. Without users, `admin` is created with a random password.

## Configuration

Bootstrap values as environment variables (`.env`, prefix `JUSTAI_`, complete list in
`backend/src/justai/config.py`). Everything else (rooms, devices, AI, plugins, languages,
retention) is maintained in the admin UI and stored in the database.

| Variable | Default | |
| --- | --- | --- |
| `JUSTAI_HTTP_PORT` | 8080 | port on the host |
| `JUSTAI_HTTPS_PORT` | 8443 | HTTPS port on the host (device app); inside the container the core always listens on 8443 |
| `JUSTAI_TLS_ENABLED` | true | HTTPS with a local certificate authority |
| `JUSTAI_TLS_NAMES` | – | additional names/addresses for the certificate, e.g. `["192.168.0.10","justai.fritz.box"]` (can also be added in the UI) |
| `JUSTAI_PUBLIC_URL` | http://localhost:8080 | with `https://` cookies become `Secure` |
| `JUSTAI_ADMIN_USERNAME` / `JUSTAI_ADMIN_PASSWORD` | admin / random | only if no user exists yet |
| `GOOGLE_API_KEY` | – | enables Gemini (can also be entered in the UI) |
| `JUSTAI_DISCOVERY_DEFAULT_CIDRS` | – | e.g. `["192.168.0.0/24"]` |
| `JUSTAI_LOG_LEVEL` | INFO | |
| `JUSTAI_ENABLE_SIMULATED_DEVICES` | true | offer the simulation driver |

### Local AI with Ollama

The plugin *OpenAI-compatible* already has an endpoint `ollama` with
`http://host.docker.internal:11434/v1` preconfigured (the core container knows
`host.docker.internal`). Start Ollama on the host and configure it to listen not only on
127.0.0.1 (`OLLAMA_HOST=0.0.0.0`). Further servers (llama.cpp, vLLM) can be added there
as additional endpoints with `locality: local`. Then assign the roles under *AI
providers*, e.g. `conversation` → Ollama model, Gemini as fallback, or `local_only`.

Choose a local model that handles tools and the languages you speak; small models often
answer in English even when spoken to in German or Italian.

## Update

```bash
git pull
docker compose up -d --build
```

Migrations run at start. Plugin configurations and granted permissions are kept. Paired
displays load the new interface by themselves after reconnecting
([DISPLAYS.md](DISPLAYS.md)). Make a backup before larger updates.

## Backup and restore

```bash
./scripts/backup.sh [target folder]       # default: ./backups
./scripts/restore.sh backups/justai5-backup-YYYYMMDD-HHMMSS.tar.gz
```

* The backup contains the database dump (`pg_dump -Fc`), the volumes `data` (plugins,
  uploaded files) and `secrets` (master key!), `docker-compose.yml` and `.env`. The file is
  written with permissions `600`. **It contains secrets: keep it encrypted and separate
  from the server.**
* Restoring stops core and sandbox, replaces the volumes and the database, takes over the
  DB password from the backup and starts everything again.
* For another Compose project: `COMPOSE_PROJECT_NAME=<name>`.

Tested (2026-10-15): backup of the running instance, restore into a **separate** Compose
project without LAN access. Rooms, devices, endpoints, plugins, automations and people
were identical, the admin login worked, and all encrypted credentials could be decrypted
with the restored master key.

## Monitoring

* `GET /api/health` (also the Docker health check of the core)
* `GET /api/system/status`: plugins, devices, media server, resources
* `GET /api/metrics`: Prometheus format
* Admin UI → *Dashboard* and *Diagnosis* (events, tasks, bus queues, audit log)
* Logs: `docker compose logs -f core` (JSON; `JUSTAI_LOG_JSON=false` for plain text)

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Device `offline` | admin UI → Devices: driver warnings; IP changed? Battery camera asleep? |
| No wakeword | *Audio*: do level and VAD move? Wakeword score when speaking? Endpoint active? Listening paused ("listen again")? |
| No sound from a camera | "Reconnect the camera" by voice or *Devices → Reconnect*; "test the speaker" ([AUDIO.md](AUDIO.md)) |
| Output does not arrive | log `output denied` with reason; with `JUSTAI_LOG_LEVEL=DEBUG` every decision as `output routed` with room, device and reason |
| The assistant hears itself | calibrate; duplex to `half`; increase `output_latency_ms` |
| Cloud AI does not answer | *Dashboard → AI providers*: paused models (orange) after errors/quota; fallback chain in *AI providers* |
| Answers in the wrong language | *AI providers*: are all spoken languages in `languages`? With a local model: does it speak the language? |
| Display shows nothing | display connected? Page visible (not in the background)? Failure reason in the tool log |
| Plugin `failed` | error text in *Plugins*, logs with `plugin=<id>` |
| Self-made plugin does not start | *Tools*: status "needs settings" → fill them in under *Plugins* |

## Uninstalling

```bash
docker compose down          # remove containers, data is kept
docker compose down -v       # CAUTION: also deletes database, secrets and data
```
