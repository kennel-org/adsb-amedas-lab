CREATE TABLE weather_site (
    code        text PRIMARY KEY,
    amedas_id   text NOT NULL,
    name        text NOT NULL,
    lat         double precision,
    lon         double precision
);

INSERT INTO weather_site (code, amedas_id, name, lat, lon) VALUES
    ('tokyo',   '44132', 'Tokyo (rep. Ikebukuro, using AMeDAS 44132)',   35.7258, 139.7299),
    ('chikura', '45401', 'Chikura (using AMeDAS Tateyama 45401)',        34.9913, 139.9663),
    ('yokohama','46106', 'Yokohama (using local AMeDAS 46106)',          35.4380, 139.6503);

