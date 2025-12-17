CREATE TABLE weather_amedas_10m (
    amedas_id   text        NOT NULL,
    obs_time    timestamptz NOT NULL,    -- UTC
    temp        real,
    precip_10m  real,
    wind_speed  real,
    wind_dir    integer,
    raw         jsonb       NOT NULL,
    PRIMARY KEY (amedas_id, obs_time)
);

