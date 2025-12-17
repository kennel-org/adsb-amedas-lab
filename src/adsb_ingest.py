#!/usr/bin/env python3
"""
Ingest ADS-B aircraft.json from dump1090-fa / SkyAware
and store into PostgreSQL adsb_aircraft table.
"""

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List

import psycopg2
import requests


# -------------------------
# Logging
# -------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

logger = logging.getLogger(__name__)


# -------------------------
# Config dataclass
# -------------------------

@dataclass
class Config:
    site_code: str
    json_url: str
    pg_host: str
    pg_port: int
    pg_db: str
    pg_user: str
    pg_password: str


def load_config() -> Config:
    """Load configuration from environment variables."""
    try:
        site_code = os.environ["SITE_CODE"]
        json_url = os.environ["JSON_URL"]
        pg_host = os.environ["PGHOST"]
        pg_port = int(os.environ.get("PGPORT", "5432"))
        pg_db = os.environ["PGDATABASE"]
        pg_user = os.environ["PGUSER"]
        pg_password = os.environ["PGPASSWORD"]
    except KeyError as e:
        raise SystemExit(f"Missing required environment variable: {e}") from e

    return Config(
        site_code=site_code,
        json_url=json_url,
        pg_host=pg_host,
        pg_port=pg_port,
        pg_db=pg_db,
        pg_user=pg_user,
        pg_password=pg_password,
    )


# -------------------------
# DB helpers
# -------------------------

def get_db_connection(cfg: Config):
    """Open a psycopg2 connection using the provided config."""
    conn = psycopg2.connect(
        host=cfg.pg_host,
        port=cfg.pg_port,
        dbname=cfg.pg_db,
        user=cfg.pg_user,
        password=cfg.pg_password,
    )
    conn.autocommit = False
    return conn


# -------------------------
# ADS-B JSON handling
# -------------------------

def fetch_aircraft_json(url: str) -> Dict[str, Any]:
    """Fetch aircraft.json from dump1090-fa / SkyAware."""
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    return resp.json()


def build_rows_from_json(
    cfg: Config,
    snapshot_time: datetime,
    data: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """
    Convert aircraft.json structure to a list of rows for adsb_aircraft.

    Expected JSON top-level structure:
    {
      "now": 1234567890.0,
      "messages": 123456,
      "aircraft": [
          {"hex": "...", "lat": ..., ...},
          ...
      ]
    }
    """
    aircraft_list = data.get("aircraft", [])
    rows: List[Dict[str, Any]] = []

    for a in aircraft_list:
        icao24 = a.get("hex")
        if not icao24:
            # Skip entries without ICAO24 address
            continue

        row: Dict[str, Any] = {
            "site_code": cfg.site_code,
            "snapshot_time": snapshot_time,
            "icao24": icao24,
            "flight": a.get("flight"),
            "squawk": a.get("squawk"),
            "lat": a.get("lat"),
            "lon": a.get("lon"),
            "alt_baro": a.get("alt_baro"),
            "gs": a.get("gs"),
            "track": a.get("track"),
            "raw": a,
        }
        rows.append(row)

    return rows


# -------------------------
# Upsert
# -------------------------

def upsert_rows(conn, rows: List[Dict[str, Any]]) -> int:
    """
    Upsert rows into adsb_aircraft using ON CONFLICT.

    Requires a UNIQUE constraint on (site_code, snapshot_time, icao24)
    in the adsb_aircraft table, for example:

        ALTER TABLE adsb_aircraft
            ADD CONSTRAINT adsb_aircraft_uniq_site_time_icao24
            UNIQUE (site_code, snapshot_time, icao24);
    """
    if not rows:
        return 0

    sql = """
        INSERT INTO adsb_aircraft (
            site_code,
            snapshot_time,
            icao24,
            flight,
            squawk,
            lat,
            lon,
            alt_baro,
            gs,
            track,
            raw
        )
        VALUES (
            %(site_code)s,
            %(snapshot_time)s,
            %(icao24)s,
            %(flight)s,
            %(squawk)s,
            %(lat)s,
            %(lon)s,
            %(alt_baro)s,
            %(gs)s,
            %(track)s,
            %(raw)s
        )
        ON CONFLICT (site_code, snapshot_time, icao24)
        DO UPDATE SET
            flight    = EXCLUDED.flight,
            squawk    = EXCLUDED.squawk,
            lat       = EXCLUDED.lat,
            lon       = EXCLUDED.lon,
            alt_baro  = EXCLUDED.alt_baro,
            gs        = EXCLUDED.gs,
            track     = EXCLUDED.track,
            raw       = EXCLUDED.raw;
    """

    with conn.cursor() as cur:
        for row in rows:
            params = {
                "site_code": row["site_code"],
                "snapshot_time": row["snapshot_time"],
                "icao24": row["icao24"],
                "flight": row["flight"],
                "squawk": row["squawk"],
                "lat": row["lat"],
                "lon": row["lon"],
                "alt_baro": row["alt_baro"],
                "gs": row["gs"],
                "track": row["track"],
                "raw": json.dumps(row["raw"]),
            }
            cur.execute(sql, params)

    conn.commit()
    return len(rows)


# -------------------------
# Main
# -------------------------

def main() -> None:
    cfg = load_config()

    logger.info("Site code: %s", cfg.site_code)
    logger.info("JSON URL: %s", cfg.json_url)
    logger.info(
        "DB target: %s@%s:%d/%s",
        cfg.pg_user,
        cfg.pg_host,
        cfg.pg_port,
        cfg.pg_db,
    )

    # Use current UTC time as the snapshot timestamp
    snapshot_time = datetime.now(timezone.utc)
    logger.info("Snapshot time (UTC): %s", snapshot_time.isoformat())

    # Fetch aircraft.json
    try:
        data = fetch_aircraft_json(cfg.json_url)
    except Exception as e:
        logger.error("Failed to fetch JSON from %s: %s", cfg.json_url, e)
        raise SystemExit(1) from e

    # Build rows
    rows = build_rows_from_json(cfg, snapshot_time, data)
    logger.info("Extracted %d aircraft rows", len(rows))

    if not rows:
        logger.info("No rows to upsert. Exiting.")
        return

    # DB upsert
    try:
        conn = get_db_connection(cfg)
    except Exception as e:
        logger.error("Failed to connect to database: %s", e)
        raise SystemExit(1) from e

    try:
        count = upsert_rows(conn, rows)
        logger.info("Upserted %d rows into adsb_aircraft", count)
    except Exception as e:
        logger.exception("Failed to upsert rows into adsb_aircraft")
        conn.rollback()
        raise SystemExit(1) from e
    finally:
        conn.close()


if __name__ == "__main__":
    main()
