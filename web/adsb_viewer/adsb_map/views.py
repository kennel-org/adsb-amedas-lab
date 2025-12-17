from django.http import JsonResponse
from django.shortcuts import render
from django.db.models import F, Window
from django.db.models.functions import RowNumber

from .models import AdsbAircraft


def map_view(request):
    """Render main map view template."""

    return render(request, "adsb_map/map.html")


def latest_points_api(request):
    """Return latest ADS-B points as JSON.

    Query parameters:
    - site: site_code filter (default: "rigel_chikura")
    - limit: max number of records to return (default: 10000)
    """

    site = request.GET.get("site")

    try:
        limit = int(request.GET.get("limit", "10000"))
    except ValueError:
        limit = 10000

    if limit <= 0:
        limit = 1

    if limit > 5000:
        limit = 5000

    base = AdsbAircraft.objects.filter(
        lat__isnull=False,
        lon__isnull=False,
    )

    if site:
        qs = (
            base.filter(site_code=site)
            .order_by("-snapshot_time")[:limit]
        )
    else:
        qs = (
            base.annotate(
                _rn=Window(
                    expression=RowNumber(),
                    partition_by=[F("site_code")],
                    order_by=F("snapshot_time").desc(),
                )
            )
            .filter(_rn__lte=limit)
            .order_by("site_code", "-snapshot_time")
        )

    results = [
        {
            "site_code": obj.site_code,
            "snapshot_time": obj.snapshot_time.isoformat().replace("+00:00", "Z"),
            "icao24": obj.icao24,
            "flight": obj.flight,
            "lat": obj.lat,
            "lon": obj.lon,
            "alt_baro": obj.alt_baro,
            "gs": obj.gs,
            "track": obj.track,
        }
        for obj in qs
    ]

    return JsonResponse({"count": len(results), "results": results})
