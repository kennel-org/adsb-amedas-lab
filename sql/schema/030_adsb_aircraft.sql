CREATE TABLE adsb_aircraft (
    id             bigint GENERATED ALWAYS AS IDENTITY,    -- technical surrogate key
    site_code      text        NOT NULL,
    snapshot_time  timestamptz NOT NULL,                   -- UTC
    icao24         text        NOT NULL,                   -- 24-bit ICAO address (from hex)
    flight         text,
    squawk         text,
    lat            double precision,
    lon            double precision,
    alt_baro       integer,
    gs             double precision,
    track          double precision,
    raw            jsonb       NOT NULL,
    -- Primary key must include the partition key (snapshot_time)
    CONSTRAINT adsb_aircraft_pk PRIMARY KEY (site_code, snapshot_time, icao24)
) PARTITION BY RANGE (snapshot_time);

-- Additional indexes for common query patterns
CREATE INDEX idx_adsb_aircraft_site_time
    ON adsb_aircraft (site_code, snapshot_time);

CREATE INDEX idx_adsb_aircraft_icao24_time
    ON adsb_aircraft (icao24, snapshot_time);

