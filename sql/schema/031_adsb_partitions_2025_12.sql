CREATE TABLE adsb_aircraft_2025_12
    PARTITION OF adsb_aircraft
    FOR VALUES FROM ('2025-12-01 00:00+00')
             TO   ('2026-01-01 00:00+00');

