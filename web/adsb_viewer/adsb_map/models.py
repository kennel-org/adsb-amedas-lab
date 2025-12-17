from django.db import models

# Create your models here.

class AdsbAircraft(models.Model):
    id = models.BigAutoField(primary_key=True)
    site_code = models.TextField()
    snapshot_time = models.DateTimeField()
    icao24 = models.TextField()
    flight = models.TextField(null=True, blank=True)
    squawk = models.TextField(null=True, blank=True)
    lat = models.FloatField(null=True, blank=True)
    lon = models.FloatField(null=True, blank=True)
    alt_baro = models.IntegerField(null=True, blank=True)
    gs = models.FloatField(null=True, blank=True)
    track = models.FloatField(null=True, blank=True)
    raw = models.JSONField()

    class Meta:
        managed = False
        db_table = "adsb_aircraft"
