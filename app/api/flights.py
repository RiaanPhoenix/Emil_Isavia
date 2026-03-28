"""
External flight-data integration.

We need to know, for every Premium-valet customer:
  • scheduled departure time  → when they drop off their car
  • scheduled arrival time    → when they need it back

The module tries real APIs first and falls back to realistic mock data
so the rest of the system always has something to work with.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from typing import List, Optional

import requests

from config import settings

log = logging.getLogger(__name__)


# ── Data model ──────────────────────────────────────────────────────

@dataclass
class ValetBooking:
    """One Premium-valet customer booking."""
    booking_id: str
    flight_out: str           # outbound flight number
    flight_in: str            # inbound flight number
    departure_time: datetime  # customer drops off car (≈ flight departure − 2 h)
    arrival_time: datetime    # customer lands back (= flight arrival)
    car_plate: str = ""
    pax_name: str = ""
    current_zone: str = ""    # current parking zone (for real API data)
    days_parked: int = 1      # number of days parked (for real API data)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["departure_time"] = self.departure_time.isoformat()
        d["arrival_time"] = self.arrival_time.isoformat()
        return d


# ── Provider implementations ────────────────────────────────────────

class FlightProvider:
    """Base class for flight-data providers."""

    def fetch_departures(self, airport: str, start: datetime, end: datetime) -> list[dict]:
        raise NotImplementedError

    def fetch_arrivals(self, airport: str, start: datetime, end: datetime) -> list[dict]:
        raise NotImplementedError


class OpenSkyProvider(FlightProvider):
    """OpenSky Network — free, no key required."""
    BASE = "https://opensky-network.org/api"

    def fetch_departures(self, airport, start, end):
        try:
            r = requests.get(
                f"{self.BASE}/flights/departure",
                params={
                    "airport": airport,
                    "begin": int(start.timestamp()),
                    "end": int(end.timestamp()),
                },
                timeout=15,
            )
            r.raise_for_status()
            return r.json()
        except Exception as exc:
            log.warning("OpenSky departures failed: %s", exc)
            return []

    def fetch_arrivals(self, airport, start, end):
        try:
            r = requests.get(
                f"{self.BASE}/flights/arrival",
                params={
                    "airport": airport,
                    "begin": int(start.timestamp()),
                    "end": int(end.timestamp()),
                },
                timeout=15,
            )
            r.raise_for_status()
            return r.json()
        except Exception as exc:
            log.warning("OpenSky arrivals failed: %s", exc)
            return []


class AviationStackProvider(FlightProvider):
    """AviationStack — requires API key."""
    BASE = "http://api.aviationstack.com/v1"

    def __init__(self, api_key: str):
        self.api_key = api_key

    def fetch_departures(self, airport, start, end):
        try:
            r = requests.get(
                f"{self.BASE}/flights",
                params={
                    "access_key": self.api_key,
                    "dep_iata": airport,
                    "limit": 100,
                },
                timeout=15,
            )
            r.raise_for_status()
            return r.json().get("data", [])
        except Exception as exc:
            log.warning("AviationStack failed: %s", exc)
            return []

    def fetch_arrivals(self, airport, start, end):
        try:
            r = requests.get(
                f"{self.BASE}/flights",
                params={
                    "access_key": self.api_key,
                    "arr_iata": airport,
                    "limit": 100,
                },
                timeout=15,
            )
            r.raise_for_status()
            return r.json().get("data", [])
        except Exception as exc:
            log.warning("AviationStack failed: %s", exc)
            return []


# ── Booking generator ───────────────────────────────────────────────

def _build_provider() -> FlightProvider:
    if settings.FLIGHT_API_KEY and settings.FLIGHT_API_PROVIDER == "aviationstack":
        return AviationStackProvider(settings.FLIGHT_API_KEY)
    return OpenSkyProvider()


def generate_bookings_from_api(
    date: Optional[datetime] = None,
    n_premium_customers: int = 60,
) -> List[ValetBooking]:
    """
    Try to pull real flight times from the API, then generate plausible
    Premium-valet bookings around them.  Falls back to mock data.
    """
    date = date or datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    start = date
    end = date + timedelta(hours=settings.PLANNING_HORIZON_H)

    provider = _build_provider()

    departures = provider.fetch_departures(settings.AIRPORT_ICAO, start, end)
    arrivals = provider.fetch_arrivals(settings.AIRPORT_ICAO, start, end)

    if departures and arrivals:
        log.info("Got %d departures and %d arrivals from API", len(departures), len(arrivals))
        return _bookings_from_real_flights(departures, arrivals, n_premium_customers, date)

    log.info("Using mock flight data (API returned no data or failed)")
    return _generate_mock_bookings(n_premium_customers, date)


def _bookings_from_real_flights(
    departures: list, arrivals: list, n: int, base_date: datetime
) -> List[ValetBooking]:
    """Pair departures with arrivals to create valet bookings."""
    bookings = []
    used_arrivals = set()
    rng = random.Random(int(base_date.strftime('%Y%m%d')))

    dep_list = departures[:n]
    for i, dep in enumerate(dep_list):
        # Try to extract departure time
        dep_time = _extract_time(dep, "departure", "firstSeen", base_date)
        if not dep_time:
            continue

        # Find a plausible return arrival (1-10 days later)
        arr = None
        for j, a in enumerate(arrivals):
            if j in used_arrivals:
                continue
            arr_time = _extract_time(a, "arrival", "lastSeen", base_date)
            if arr_time and arr_time > dep_time + timedelta(hours=2):
                arr = a
                used_arrivals.add(j)
                break

        if arr is None:
            # Create a synthetic return flight
            arr_time = dep_time + timedelta(days=rng.randint(1, 7), hours=rng.randint(0, 12))
        else:
            arr_time = _extract_time(arr, "arrival", "lastSeen", base_date)

        # Customer drops off ≈ 2 hours before departure
        drop_off_time = dep_time - timedelta(hours=2, minutes=rng.randint(0, 30))

        bookings.append(ValetBooking(
            booking_id=f"PV-{i+1:04d}",
            flight_out=dep.get("callsign", dep.get("flight", {}).get("iata", f"FI{100+i}")).strip(),
            flight_in=arr.get("callsign", f"FI{200+i}").strip() if arr else f"FI{200+i}",
            departure_time=drop_off_time,
            arrival_time=arr_time,
            car_plate=f"IS-{rng.choice('ABCDEFGHJKLMNPRSTUVWXY')}{rng.randint(100,999)}",
        ))

    return bookings


def _extract_time(flight_data: dict, dep_or_arr: str, fallback_key: str, base: datetime) -> Optional[datetime]:
    """Extract a datetime from various API response shapes."""
    # OpenSky shape
    ts = flight_data.get(fallback_key)
    if ts and isinstance(ts, (int, float)):
        return datetime.utcfromtimestamp(ts)

    # AviationStack shape
    nested = flight_data.get(dep_or_arr, {})
    if isinstance(nested, dict):
        scheduled = nested.get("scheduled")
        if scheduled:
            try:
                return datetime.fromisoformat(scheduled.replace("Z", "+00:00")).replace(tzinfo=None)
            except Exception:
                pass

    return None


def _generate_mock_bookings(n: int, base_date: datetime) -> List[ValetBooking]:
    """
    Create realistic mock bookings spread across the planning horizon.
    Mimics Keflavík traffic patterns (busy morning departures, afternoon arrivals).
    """
    # Seed from the date so each day produces different but reproducible bookings
    date_seed = int(base_date.strftime('%Y%m%d'))
    rng = random.Random(date_seed)
    bookings = []

    # Typical Keflavík departure waves (hour, relative_weight)
    dep_waves = [(6, 3), (7, 5), (8, 4), (9, 3), (10, 2),
                 (11, 2), (14, 3), (15, 4), (16, 5), (17, 3), (20, 2)]
    total_weight = sum(w for _, w in dep_waves)

    for i in range(n):
        # Pick a departure wave weighted by traffic pattern
        r = rng.uniform(0, total_weight)
        cumulative = 0
        dep_hour = 10  # default
        for hour, weight in dep_waves:
            cumulative += weight
            if r <= cumulative:
                dep_hour = hour
                break

        dep_minute = rng.randint(0, 59)
        dep_time = base_date + timedelta(hours=dep_hour, minutes=dep_minute)

        # Customer drops off 1.5-3 hours before departure
        drop_off = dep_time - timedelta(minutes=rng.randint(90, 180))

        # Trip duration: 1-10 days
        trip_days = rng.choices([1, 2, 3, 4, 5, 7, 10], weights=[5, 4, 3, 2, 2, 1, 1])[0]
        # Return arrival time
        arr_hour = rng.choice([6, 7, 8, 9, 10, 14, 15, 16, 17, 20, 21, 22])
        arr_minute = rng.randint(0, 59)
        arrival = base_date + timedelta(days=trip_days, hours=arr_hour, minutes=arr_minute)

        bookings.append(ValetBooking(
            booking_id=f"PV-{i+1:04d}",
            flight_out=f"FI{rng.randint(100,699)}",
            flight_in=f"FI{rng.randint(700,999)}",
            departure_time=drop_off,
            arrival_time=arrival,
            car_plate=f"IS-{rng.choice('ABCDEFGHJKLMNPRSTUVWXY')}{rng.randint(100,999)}",
        ))

    bookings.sort(key=lambda b: b.departure_time)
    return bookings
