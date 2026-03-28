# ADS-B + AMeDAS Lab

This repository contains code and database schema for a small lab environment that collects:

- ADS-B data (from multiple receiver sites)
- AMeDAS 10-minute weather data (from JMA)

and stores them into a single PostgreSQL database.

Example ADS-B map view from the development web viewer:

![ADS-B map example](docs/images/adsb_map_example.png)

For detailed requirements and architecture, see the documents under `docs/`:
- `docs/architecture.md`
- `docs/adsb_amedas_requirements.md`

## Repository layout

- `src/`
  - `amedas_ingest.py`: Fetches recent 10-minute AMeDAS observations and UPSERTs into `weather_amedas_10m`.
  - `amedas_backfill.py`: Backfill script to fetch historical AMeDAS data.
  - `adsb_ingest.py`: Fetches `aircraft.json` from dump1090-fa / SkyAware and UPSERTs into `adsb_aircraft`.
- `sql/schema/`
  - PostgreSQL schema definitions and initial data, e.g. `010_weather_site.sql`.
- `docs/`
  - Architecture and requirements documents.
- `.env.sample`
  - Sample environment variables for the app_server. The real `.env` file is **not** tracked by Git.
- `.env.web.sample`
  - Sample database connection settings for the Django development web viewer under `web/adsb_viewer/` (the real `.env.web` is **not** tracked by Git).
- `config/`
  - Per-host configuration directories. Real production host directories are ignored by Git.
- `web/adsb_viewer/`
  - Django 4.2-based development web viewer for ADS-B maps. The `adsb_viewer.settings` module uses fixed values for `NAME="adsb_test"`, `USER="lab_ro"`, `HOST="127.0.0.1"`, `PORT="5432"`, and reads the password from the `PGPASSWORD` environment variable.

## Setup (overview)

### 1. Prepare Python environment

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Note: The shared top-level `requirements.txt` already includes the main libraries needed for database access and the web viewer (such as `requests`, `psycopg2-binary`, `python-dateutil`, and `Django`). If you need additional libraries for your own experiments, install them separately in your environment.

### 2. Create `.env` for the app_server

Create your real `.env` from the sample at the repository root:

```bash
cp .env.sample .env
# Edit .env and set PGHOST and other values for your environment
```

- `.env` is excluded by `.gitignore` and **must not** be committed.
- Database connection info and passwords should live only in `.env`.

### 3. Create per-host config directories for ADS-B sites

For each ADS-B receiver host, create a directory under `config/` and place `env/` and `systemd/` files there.

Example (replace names with your own host/site names):

```text
config/
  my_site1/
    env/
      adsb.env        # This file must not be tracked by Git
    systemd/
      adsb-ingest.service
      adsb-ingest.timer
  my_app_server/
    systemd/
      amedas-ingest.service
      amedas-ingest.timer
```

In the original private environment, host-specific directories such as `config/rigel/` and `config/canopus/` are used. In this public repository, those directories are **excluded via `.gitignore`** to avoid leaking real host names and settings.

When you use this repository, create your own `config/<your_host>/` directory and place your `env/adsb.env` and `systemd/` files there.

- `env/adsb.env` is excluded by the `.gitignore` pattern `config/*/env/*.env`.
- In the systemd unit files, adjust `WorkingDirectory`, `User`, and other fields to match your environment.

### 4. Running the batch scripts

Examples for running the scripts manually during development:

- AMeDAS ingestion (on app_server):

```bash
dotenvx run -- python src/amedas_ingest.py
```

- ADS-B ingestion (on each ADS-B host):

```bash
dotenvx run -- env-file config/<your_site>/env/adsb.env -- python src/adsb_ingest.py
```

For production use, refer to the docs for `systemd service + timer` configuration and run the scripts periodically.

### 5. Development web viewer (Django `adsb_viewer`)

On the app_server host, you can run a **development web viewer** using Django. It reads from `adsb_test.adsb_aircraft` and plots recent aircraft positions on a map.

Notes (viewer API behavior):

- `/api/latest/` returns ADS-B points as JSON.
  - Query parameters:
    - `site`: filter by `site_code` when provided
    - `limit`: per-site max rows to return (clamped to **max 5000 rows per site**)
  - If `site` is omitted, the API returns the **latest `limit` rows for each `site_code`** found in the database.
    - Example: if there are two sites and `limit=5000`, the response may include up to 10000 rows.
- On the client side (`adsb_map/templates/adsb_map/map.html`), points are grouped by `icao24` and rendered as tracks.
  - By default, only the longest tracks are drawn (top K by number of points) via `TOP_K_TRACKS=100`.
  - Track colors indicate temporal order (older → newer) using a `d3.interpolateTurbo` gradient along each track.
  - To avoid unrealistic straight-line interpolation across missing data, segments are skipped when the time gap between consecutive points exceeds a threshold. The current default is `MAX_GAP_SEC=60` (break when gap is greater than 60 seconds).

#### 5.1 Setup (overview)

```bash
cd /path/to/adsb-amedas-lab/web/adsb_viewer

# Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies (Django 4.2, psycopg2-binary, etc.)
pip install -r ../../requirements.txt

# Create the actual .env.web from the sample
cp ../../.env.web.sample ../../.env.web
# Edit ../../.env.web and set PGHOST / PGPORT / PGDATABASE / PGUSER / PGPASSWORD for your environment
```

- In `web/adsb_viewer/adsb_viewer/settings.py`, the `DATABASES["default"]` configuration:
  - uses defaults of `NAME=adsb_test`, `USER=lab_ro`, `HOST=127.0.0.1`, and `PORT=5432`;
  - lets `PGDATABASE`, `PGUSER`, `PGHOST`, `PGPORT`, and `PGPASSWORD` override those defaults when set;
  - falls back to libpq's standard `~/.pgpass` handling when `PGPASSWORD` is not set.
- `run_dev_server.sh` sources the repository root `.env.web` and then starts Django, so create `.env.web` from `.env.web.sample` when you need to provide PG* variables explicitly.
- `run_dev_server.sh` resolves the repository root from its own location, so the clone does not need to live at `~/adsb-amedas-lab`.

#### 5.2 How to start the development server

- Manual start (during development):

  ```bash
  cd /path/to/adsb-amedas-lab/web/adsb_viewer
  ./run_dev_server.sh
  ```

  This script reads `.env.web`, activates `.venv`, and runs `python manage.py runserver 0.0.0.0:8000`.

- Automatic start via systemd (development use):

  Example unit file `/etc/systemd/system/adsb-viewer.service`:

  ```ini
  [Unit]
  Description=ADS-B Django viewer dev server
  After=network.target postgresql.service
  Wants=network-online.target

  [Service]
  Type=simple
  User=<your_user>
  Group=<your_user>
  WorkingDirectory=/path/to/adsb-amedas-lab/web/adsb_viewer
  ExecStart=/usr/bin/bash /path/to/adsb-amedas-lab/web/adsb_viewer/run_dev_server.sh
  Restart=on-failure
  Environment=PYTHONUNBUFFERED=1

  [Install]
  WantedBy=multi-user.target
  ```

  Enable and start:

  ```bash
  sudo systemctl daemon-reload
  sudo systemctl enable --now adsb-viewer.service
  ```

  After that, the Django viewer will be automatically started on boot by `adsb-viewer.service`.

#### 5.3 systemd control examples

```bash
# Start / stop
sudo systemctl start adsb-viewer.service
sudo systemctl stop adsb-viewer.service

# Check status
systemctl status adsb-viewer.service

# View logs (tail)
journalctl -u adsb-viewer.service -e

# Disable auto-start (and stop the current service)
sudo systemctl disable --now adsb-viewer.service
```

## Notes on public usage

- Do **not** commit any real host names, user names, passwords, or other secrets.
  - Keep them only in `.env` and `config/*/env/*.env`.
- Real per-host directories such as `config/rigel/` or `config/canopus/` are **not included** in this public repository.
  - `.gitignore` ensures these directories are ignored.
- If you fork or clone this repository, you will need to:
  - Create your own `config/<your_host>/` directory (or directories) with `env/` and `systemd/` files.
  - Create `.env` from `.env.sample` at the repository root.

This way, the repository can be public while all environment-specific and secret information stays in your private configuration files.
