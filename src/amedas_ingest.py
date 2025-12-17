import os
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional

import requests
import psycopg2
from psycopg2.extras import register_default_jsonb


# Register jsonb handling for psycopg2
register_default_jsonb()

LATEST_TIME_URL = "https://www.jma.go.jp/bosai/amedas/data/latest_time.txt"
POINT_URL_TEMPLATE = "https://www.jma.go.jp/bosai/amedas/data/point/{amedas_id}/{date_hour}.json"


@dataclass
class DbConfig:
    host: str
    port: int
    dbname: str
    user: str
    password: str


def load_db_config_from_env() -> DbConfig:
    """Load database configuration from environment variables."""
    return DbConfig(
        host=os.environ.get("PGHOST", "localhost"),
        port=int(os.environ.get("PGPORT", "5432")),
        dbname=os.environ.get("PGDATABASE", "adsb_test"),
        user=os.environ.get("PGUSER", "lab_rw"),
        password=os.environ["PGPASSWORD"],
    )


def load_amedas_ids_from_env() -> List[str]:
    """Load target AMeDAS station IDs from environment variable."""
    ids = os.environ.get("AMEDAS_IDS", "")
    return [s.strip() for s in ids.split(",") if s.strip()]


def get_latest_time() -> datetime:
    """Fetch the latest AMeDAS observation time from JMA (JST)."""
    resp = requests.get(LATEST_TIME_URL, timeout=5)
    resp.raise_for_status()
    text = resp.text.strip()
    # Example: 2025-12-07T00:20:00+09:00
    dt = datetime.fromisoformat(text)
    return dt


def get_block_start(time_jst: datetime) -> datetime:
    """
    Get the 3-hour block start time for the given datetime (keeping tzinfo).

    AMeDAS point data is provided in 3-hour blocks:
    00, 03, 06, 09, 12, 15, 18, 21 (JST).
    """
    hour_block = (time_jst.hour // 3) * 3
    return time_jst.replace(hour=hour_block, minute=0, second=0, microsecond=0)


def fetch_point_block(amedas_id: str, block_start: datetime) -> Dict[str, Any]:
    """
    Fetch a 3-hour block of 10-minute AMeDAS data for a single station.

    The URL format is:
      /bosai/amedas/data/point/{amedas_id}/{YYYYMMDD_HH}.json
    where the hour is the start of a 3-hour block in JST.
    """
    date_hour = block_start.strftime("%Y%m%d_%H")
    url = POINT_URL_TEMPLATE.format(amedas_id=amedas_id, date_hour=date_hour)
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    return resp.json()


def parse_value(entry: Dict[str, Any], key: str) -> Optional[float]:
    """
    Extract the first element of a [value, flag] array, or None.

    Many AMeDAS fields are represented as:
      "temp": [value, flag]
    This function returns "value" or None.
    """
    if key not in entry:
        return None
    arr = entry.get(key)
    if not isinstance(arr, list) or not arr:
        return None
    return arr[0]


def parse_obs_time(time_str: str) -> Optional[datetime]:
    """
    Parse an AMeDAS observation time key.

    Supported formats:
      - "YYYY-MM-DDTHH:MM:SS+09:00" (ISO format with JST offset)
      - "YYYYMMDDHHMMSS" (14-digit JMA format, JST without explicit offset)
    """
    # ISO 8601 style (already contains offset like +09:00)
    if "T" in time_str:
        try:
            return datetime.fromisoformat(time_str)
        except ValueError:
            return None

    # JMA 14-digit numeric style: YYYYMMDDHHMMSS (assumed JST)
    if len(time_str) == 14 and time_str.isdigit():
        try:
            dt_naive = datetime.strptime(time_str, "%Y%m%d%H%M%S")
            jst = timezone(timedelta(hours=9))
            return dt_naive.replace(tzinfo=jst)
        except ValueError:
            return None

    return None


def upsert_amedas_block(
    conn,
    amedas_id: str,
    data: Dict[str, Any],
) -> int:
    """
    Upsert one 3-hour block of AMeDAS data into weather_amedas_10m.

    Returns number of rows processed.
    """
    rows = 0
    with conn.cursor() as cur:
        for time_str, entry in data.items():
            obs_time_local = parse_obs_time(time_str)
            if obs_time_local is None:
                logging.warning("Skip invalid time string: %s", time_str)
                continue

            # Convert to UTC to normalize storage
            obs_time_utc = obs_time_local.astimezone(timezone.utc)

            temp = parse_value(entry, "temp")
            precip_10m = parse_value(entry, "precipitation10m")
            wind_speed = parse_value(entry, "wind")
            wind_dir = parse_value(entry, "windDirection")

            raw_json = json.dumps(entry, ensure_ascii=False)

            cur.execute(
                """
                INSERT INTO weather_amedas_10m
                    (amedas_id, obs_time, temp, precip_10m, wind_speed, wind_dir, raw)
                VALUES
                    (%s, %s, %s, %s, %s, %s, %s::jsonb)
                ON CONFLICT (amedas_id, obs_time) DO UPDATE
                SET temp = EXCLUDED.temp,
                    precip_10m = EXCLUDED.precip_10m,
                    wind_speed = EXCLUDED.wind_speed,
                    wind_dir = EXCLUDED.wind_dir,
                    raw = EXCLUDED.raw
                """,
                (amedas_id, obs_time_utc, temp, precip_10m, wind_speed, wind_dir, raw_json),
            )
            rows += 1
    return rows


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    db_cfg = load_db_config_from_env()
    amedas_ids = load_amedas_ids_from_env()
    if not amedas_ids:
        logging.error("AMEDAS_IDS is not set or empty.")
        return

    logging.info("Target AMeDAS IDs: %s", ", ".join(amedas_ids))

    latest_jst = get_latest_time()
    logging.info("Latest AMeDAS time (JST): %s", latest_jst.isoformat())

    block_start = get_block_start(latest_jst)
    logging.info("Using 3-hour block starting at (JST): %s", block_start.isoformat())

    conn = psycopg2.connect(
        host=db_cfg.host,
        port=db_cfg.port,
        dbname=db_cfg.dbname,
        user=db_cfg.user,
        password=db_cfg.password,
    )
    try:
        total_rows = 0
        for amedas_id in amedas_ids:
            logging.info("Fetching AMeDAS block for %s", amedas_id)
            try:
                block_data = fetch_point_block(amedas_id, block_start)
            except requests.HTTPError as e:
                logging.error("HTTP error for %s: %s", amedas_id, e)
                continue
            except requests.RequestException as e:
                logging.error("Request error for %s: %s", amedas_id, e)
                continue

            n = upsert_amedas_block(conn, amedas_id, block_data)
            total_rows += n
            logging.info("Upserted %d rows for %s", n, amedas_id)

        conn.commit()
        logging.info("Done. Total upserted rows: %d", total_rows)
    finally:
        conn.close()


if __name__ == "__main__":
    main()

