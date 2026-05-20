from __future__ import annotations

import os
from pathlib import Path
from datetime import timezone
from typing import Any, Optional

import psycopg2
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from psycopg2.extras import RealDictCursor


APP_DIR = Path(__file__).resolve().parent
MAP_HTML = APP_DIR / "static" / "map.html"

app = FastAPI(title="ADS-B Map Viewer")


def db_connect():
    return psycopg2.connect(
        host=os.environ.get("PGHOST", "127.0.0.1"),
        port=int(os.environ.get("PGPORT", "5432")),
        dbname=os.environ.get("PGDATABASE", "adsb_test"),
        user=os.environ.get("PGUSER", "lab_ro"),
        password=os.environ.get("PGPASSWORD") or None,
    )


def normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    snapshot_time = row["snapshot_time"].astimezone(timezone.utc)
    return {
        "site_code": row["site_code"],
        "snapshot_time": snapshot_time.isoformat().replace("+00:00", "Z"),
        "icao24": row["icao24"],
        "flight": row["flight"],
        "lat": row["lat"],
        "lon": row["lon"],
        "alt_baro": row["alt_baro"],
        "gs": row["gs"],
        "track": row["track"],
    }


@app.get("/")
def map_view():
    if not MAP_HTML.exists():
        raise HTTPException(status_code=500, detail="map.html is missing")
    return FileResponse(MAP_HTML, media_type="text/html")


@app.get("/api/latest/")
def latest_points_api(
    site: Optional[str] = None,
    limit: int = Query(default=10000),
):
    if limit <= 0:
        limit = 1
    if limit > 5000:
        limit = 5000

    if site:
        sql = """
            SELECT site_code, snapshot_time, icao24, flight, lat, lon, alt_baro, gs, track
            FROM adsb_aircraft
            WHERE lat IS NOT NULL
              AND lon IS NOT NULL
              AND site_code = %s
            ORDER BY snapshot_time DESC
            LIMIT %s
        """
        params: tuple[Any, ...] = (site, limit)
    else:
        sql = """
            SELECT site_code, snapshot_time, icao24, flight, lat, lon, alt_baro, gs, track
            FROM (
                SELECT
                    site_code,
                    snapshot_time,
                    icao24,
                    flight,
                    lat,
                    lon,
                    alt_baro,
                    gs,
                    track,
                    row_number() OVER (
                        PARTITION BY site_code
                        ORDER BY snapshot_time DESC
                    ) AS rn
                FROM adsb_aircraft
                WHERE lat IS NOT NULL
                  AND lon IS NOT NULL
            ) latest
            WHERE rn <= %s
            ORDER BY site_code ASC, snapshot_time DESC
        """
        params = (limit,)

    try:
        with db_connect() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
    except psycopg2.Error as exc:
        raise HTTPException(status_code=503, detail="database query failed") from exc

    results = [normalize_row(dict(row)) for row in rows]
    return JSONResponse({"count": len(results), "results": results})
