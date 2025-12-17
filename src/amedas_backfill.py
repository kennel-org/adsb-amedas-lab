# src/amedas_backfill.py

import logging
from datetime import datetime, timedelta, timezone

from amedas_ingest import (
    load_db_config_from_env,
    load_amedas_ids_from_env,
    fetch_point_block,
    upsert_amedas_block,
)

import psycopg2


def iter_blocks(end_jst: datetime, hours_back: int):
    """Yield 3-hour block start times going back from end_jst."""
    # Align to 3-hour block boundary
    aligned = end_jst.replace(minute=0, second=0, microsecond=0)
    aligned = aligned.replace(hour=(aligned.hour // 3) * 3)
    blocks = hours_back // 3

    for i in range(blocks + 1):
        yield aligned - timedelta(hours=3 * i)


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

    # Example: backfill last 24 hours (8 blocks)
    hours_back = 240
    now_jst = datetime.now(timezone(timedelta(hours=9)))
    logging.info("Backfilling last %d hours from %s (JST)", hours_back, now_jst.isoformat())

    conn = psycopg2.connect(
        host=db_cfg.host,
        port=db_cfg.port,
        dbname=db_cfg.dbname,
        user=db_cfg.user,
        password=db_cfg.password,
    )

    try:
        total_rows = 0
        for block_start in iter_blocks(now_jst, hours_back):
            logging.info("Processing block starting at (JST): %s", block_start.isoformat())
            for amedas_id in amedas_ids:
                logging.info("  Station %s", amedas_id)
                try:
                    block_data = fetch_point_block(amedas_id, block_start)
                except Exception as e:
                    logging.warning("  Skip station %s at %s: %s", amedas_id, block_start, e)
                    continue

                n = upsert_amedas_block(conn, amedas_id, block_data)
                total_rows += n
                logging.info("  Upserted %d rows", n)

        conn.commit()
        logging.info("Backfill done. Total upserted rows: %d", total_rows)
    finally:
        conn.close()


if __name__ == "__main__":
    main()

