"""
greedy_scheduler.py
===================
Greedy valet day-plan scheduler (FIFO ordering).

Extracted from isavia_valet.py for web integration.
Travel times are pulled from config/settings instead of a CSV file.

Public interface
----------------
    schedule_day(day_str: str) -> dict
        Returns:
            {
                "date": str,
                "tasks": list[dict],
                "warnings": list[str],
                "summary": dict,
                "storage": str,
            }
"""

import bisect
import base64
import json
import os
import urllib.request
from datetime import datetime, timedelta
from typing import Dict, List, Tuple

from dotenv import load_dotenv
from config import settings

load_dotenv()

# ─────────────────────────────────────────────────────────
# CONSTANTS — pulled from settings / env
# ─────────────────────────────────────────────────────────
API_URL      = os.getenv("PARKING_API_URL", "https://parking-api-dev-d8b2ejb0asc0gbec.northeurope-01.azurewebsites.net")
API_USER     = os.getenv("PARKING_API_USERNAME", "")
API_PASSWORD = os.getenv("PARKING_API_PASSWORD", "")
_AUTH        = "Basic " + base64.b64encode(f"{API_USER}:{API_PASSWORD}".encode()).decode()

NUM_WORKERS       = 2
PROCESS_MIN       = 1.5   # key-box handling time (minutes)
DROPOFF_BEFORE_H  = 3     # customer drops off N hours before departure
MOVE2_WINDOW_MIN  = 60    # retrieval window: start no earlier than arr - 60 min

LOC_OFFICE = "Office"
LOC_MOTT   = "Móttökustæði"
LOC_GULL   = "Gull"
LOC_P3     = "P3"
LOC_SKIL   = "Skilastæði"

# Travel times (minutes) built from settings.py values
# walk dict:  (from, to) -> minutes (walking)
# drive dict: (from, to) -> minutes (driving a car)
_WALK: Dict[Tuple[str, str], float] = {
    (LOC_OFFICE, LOC_MOTT):  0.0,                                  # office is at reception
    (LOC_MOTT,  LOC_OFFICE): 0.0,
    (LOC_OFFICE, LOC_GULL):  settings.WALK_GULL_TO_RECEPTION,      # same distance back
    (LOC_GULL,  LOC_OFFICE): settings.WALK_GULL_TO_RECEPTION,
    (LOC_OFFICE, LOC_P3):    settings.WALK_P3_TO_RECEPTION,
    (LOC_P3,    LOC_OFFICE): settings.WALK_P3_TO_RECEPTION,
    (LOC_OFFICE, LOC_SKIL):  settings.WALK_DELIVERY_TO_GULL,       # approximate
    (LOC_SKIL,  LOC_OFFICE): settings.WALK_DELIVERY_TO_GULL,
}

_DRIVE: Dict[Tuple[str, str], float] = {
    (LOC_MOTT, LOC_GULL): settings.TRAVEL_RECEPTION_TO_GULL,
    (LOC_GULL, LOC_MOTT): settings.TRAVEL_RECEPTION_TO_GULL,
    (LOC_MOTT, LOC_P3):   settings.TRAVEL_RECEPTION_TO_P3,
    (LOC_P3,   LOC_MOTT): settings.TRAVEL_RECEPTION_TO_P3,
    (LOC_GULL, LOC_SKIL): settings.TRAVEL_GULL_TO_DELIVERY,
    (LOC_SKIL, LOC_GULL): settings.TRAVEL_GULL_TO_DELIVERY,
    (LOC_P3,   LOC_SKIL): settings.TRAVEL_P3_TO_DELIVERY,
    (LOC_SKIL, LOC_P3):   settings.TRAVEL_P3_TO_DELIVERY,
}


# ─────────────────────────────────────────────────────────
# CAR
# ─────────────────────────────────────────────────────────
class Car:
    def __init__(self, car_id: str, dep: datetime, arr: datetime):
        self.car_id     = car_id
        self.dep_flight = dep
        self.arr_flight = arr
        self.dropoff    = dep - timedelta(hours=DROPOFF_BEFORE_H)
        self.storage_ddl = dep          # must be stored by departure time
        self.return_ddl  = arr

    def __repr__(self):
        return f"Car({self.car_id})"


# ─────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────
def _fmt(t: datetime) -> str:
    return t.strftime("%Y-%m-%d %H:%M")


def _parse_dt(s: str) -> datetime:
    s = str(s).strip().replace("T", " ").split(".")[0].split("+")[0].replace("Z", "").strip()
    for fmt in (
        "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d",
        "%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%Y",
        "%d/%m/%Y %H:%M", "%m/%d/%Y %H:%M",
    ):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    raise ValueError(f"Cannot parse datetime: {s!r}")


def _norm(s: str) -> str:
    return s.lower().replace("_", "").replace(" ", "")


def _travel(d: Dict, a: str, b: str) -> float:
    if (a, b) in d:
        return d[(a, b)]
    if (b, a) in d:
        return d[(b, a)]
    raise KeyError(f"No travel time for '{a}' <-> '{b}'")


def _mission_dur(frm: str, to: str) -> float:
    """Total time for one staff member to drive a car from frm to to and walk back."""
    return _travel(_WALK, LOC_OFFICE, frm) + PROCESS_MIN + _travel(_DRIVE, frm, to) + _travel(_WALK, to, LOC_OFFICE)


def _to_mins(midnight: datetime, t: datetime) -> float:
    return (t - midnight).total_seconds() / 60.0


def _slot_free(intervals: list, start: float, end: float) -> bool:
    return all(end <= a or start >= b for a, b in intervals)


def _find_slot(busy: list, latest: float, floor: float, dur: float, day_end: float):
    """Search backwards from latest for a free slot of length dur."""
    candidate = min(day_end - dur, latest)
    while candidate >= floor:
        if _slot_free(busy, candidate, candidate + dur):
            return candidate
        candidate -= 5
    return None


# ─────────────────────────────────────────────────────────
# API
# ─────────────────────────────────────────────────────────
def _api_get(endpoint: str):
    url = API_URL.rstrip("/") + "/" + endpoint.lstrip("/")
    req = urllib.request.Request(url, headers={"Authorization": _AUTH, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


# ─────────────────────────────────────────────────────────
# PARSE RECORDS → Cars
# ─────────────────────────────────────────────────────────
def _parse_records(records: list, id_keys, dep_keys, arr_keys, day_str: str) -> List[Car]:
    day  = datetime.strptime(day_str, "%Y-%m-%d")
    day0 = day.replace(hour=0,  minute=0,  second=0, microsecond=0)
    day1 = day.replace(hour=23, minute=59, second=0, microsecond=0)

    def pick(rec, keys):
        for k in keys:
            if k in rec and rec[k] not in (None, ""):
                return str(rec[k])
        for k in keys:
            for rk in rec:
                if _norm(k) in _norm(rk) and rec[rk] not in (None, ""):
                    return str(rec[rk])
        return None

    cars, skipped = [], 0
    for rec in records:
        cid     = pick(rec, id_keys)
        dep_raw = pick(rec, dep_keys)
        arr_raw = pick(rec, arr_keys)
        if not cid or not dep_raw or not arr_raw:
            skipped += 1
            continue
        try:
            dep = _parse_dt(dep_raw)
            arr = _parse_dt(arr_raw)
        except ValueError:
            skipped += 1
            continue
        if dep > arr:
            dep, arr = arr, dep
        c = Car(cid, dep, arr)
        # Include car if dropoff, departure, or return touches this day
        if (day0 <= c.dropoff <= day1) or (day0 <= c.dep_flight < day1) or (day0 <= c.return_ddl <= day1):
            cars.append(c)

    return cars, skipped


# ─────────────────────────────────────────────────────────
# LOAD CARS FROM API
# ─────────────────────────────────────────────────────────
def _load_cars(day_str: str) -> Tuple[List[Car], str]:
    """Returns (cars, source) where source is 'api' or 'error'."""
    ID  = ["carId", "car_id", "CarId", "id", "bookingId", "licensePlate", "plateNumber"]
    DEP = ["departure", "departureFlight", "dep", "departureTime", "departureDate", "Departure"]
    ARR = ["arrival", "arrivalFlight", "arr", "arrivalTime", "arrivalDate", "Arrival", "returnDate"]

    # Look back 30 days to catch cars dropped off earlier that return today
    day_dt   = datetime.strptime(day_str, "%Y-%m-%d")
    lookback = (day_dt - timedelta(days=30)).strftime("%Y-%m-%d")
    ep = f"/premium-bookings?date_start={lookback}&date_end={day_str}"
    try:
        result = _api_get(ep)
        raw = result if isinstance(result, list) else (
            result.get("data") or result.get("bookings") or result.get("reservations") or []
        )
        cars, skipped = _parse_records(raw, ID, DEP, ARR, day_str)
        return cars, "api", skipped
    except Exception as e:
        return [], f"api_error: {e}", 0


# ─────────────────────────────────────────────────────────
# ADD ROW TO TASK LIST
# ─────────────────────────────────────────────────────────
def _add_row(rows: list, move_type: str, car: Car, storage: str,
             worker: int, start_min: float, duration: float, midnight: datetime):
    if move_type == "MOVE1":
        frm = LOC_MOTT
        to  = LOC_GULL if storage == "Gull" else LOC_P3
    else:
        frm = LOC_GULL if storage == "Gull" else LOC_P3
        to  = LOC_SKIL
    start_dt = midnight + timedelta(minutes=start_min)
    rows.append({
        "type":            move_type,
        "carId":           car.car_id,
        "storage":         storage,
        "worker":          f"W{worker + 1}",
        "start":           _fmt(start_dt),
        "end":             _fmt(start_dt + timedelta(minutes=duration)),
        "durationMin":     round(duration, 1),
        "move":            f"{frm} → {to}",
        "depFlight":       _fmt(car.dep_flight),
        "arrFlight":       _fmt(car.arr_flight),
        "storageDeadline": _fmt(car.storage_ddl),
        "returnDeadline":  _fmt(car.return_ddl),
    })


# ─────────────────────────────────────────────────────────
# GREEDY SCHEDULER
# ─────────────────────────────────────────────────────────
def _greedy_schedule(cars: List[Car], midnight: datetime) -> Tuple[list, list]:
    dur_mott_gull = _mission_dur(LOC_MOTT, LOC_GULL)
    dur_mott_p3   = _mission_dur(LOC_MOTT, LOC_P3)
    dur_gull_skil = _mission_dur(LOC_GULL, LOC_SKIL)
    dur_p3_skil   = _mission_dur(LOC_P3,   LOC_SKIL)

    day_end = 1440.0
    rows, warnings = [], []
    worker_busy = [[] for _ in range(NUM_WORKERS)]
    day0 = midnight
    day1 = midnight + timedelta(days=1)

    # Pick storage zone: whichever makes the full round-trip shorter
    storage   = "Gull" if (dur_mott_gull + dur_gull_skil) <= (dur_mott_p3 + dur_p3_skil) else "P3"
    move1_dur = dur_mott_gull if storage == "Gull" else dur_mott_p3
    move2_dur = dur_gull_skil if storage == "Gull" else dur_p3_skil

    # ── MOVE2 pass: schedule retrievals (storage → delivery) ──────────
    # Sort by arrival so earliest returns get scheduled first
    move2_cars = sorted(
        [c for c in cars if day0 <= c.arr_flight < day1],
        key=lambda c: c.arr_flight,
    )
    for car in move2_cars:
        window_start = max(0.0, _to_mins(midnight, car.arr_flight - timedelta(minutes=MOVE2_WINDOW_MIN)))
        latest_start = _to_mins(midnight, car.arr_flight) - move2_dur

        best_choice = None
        for w in range(NUM_WORKERS):
            t = _find_slot(worker_busy[w], latest_start, window_start, move2_dur, day_end)
            if t is not None and (best_choice is None or t > best_choice[0]):
                best_choice = (t, w)

        started_early = False
        if best_choice is None:
            # Fall back: allow starting before the 60-min window
            for w in range(NUM_WORKERS):
                t = _find_slot(worker_busy[w], latest_start, 0.0, move2_dur, day_end)
                if t is not None and (best_choice is None or t > best_choice[0]):
                    best_choice = (t, w)
            started_early = best_choice is not None

        if best_choice is None:
            warnings.append(f"{car.car_id}: no MOVE2 slot found")
            continue

        if started_early:
            warnings.append(
                f"{car.car_id}: MOVE2 starts early "
                f"({_fmt(midnight + timedelta(minutes=best_choice[0]))}) — high load"
            )

        start, w = best_choice
        bisect.insort(worker_busy[w], (start, start + move2_dur))
        _add_row(rows, "MOVE2", car, storage, w, start, move2_dur, midnight)

    # ── MOVE1 pass: schedule drop-offs (reception → storage) ──────────
    # Sort by dropoff time (FIFO)
    move1_cars = sorted(
        [c for c in cars if day0 <= c.dropoff < day1],
        key=lambda c: c.dropoff,
    )
    for car in move1_cars:
        release  = max(0.0, _to_mins(midnight, car.dropoff))
        deadline = min(day_end, _to_mins(midnight, car.storage_ddl))

        best_choice = None
        for w in range(NUM_WORKERS):
            candidate = release
            for busy_start, busy_end in worker_busy[w]:
                if candidate + move1_dur <= busy_start:
                    break
                if candidate < busy_end:
                    candidate = busy_end
            end = candidate + move1_dur
            if end <= day_end and (best_choice is None or candidate < best_choice[0]):
                best_choice = (candidate, w)

        if best_choice is None:
            warnings.append(f"{car.car_id}: no MOVE1 slot found")
            continue

        start, w = best_choice
        bisect.insort(worker_busy[w], (start, start + move1_dur))

        if start + move1_dur > deadline:
            warnings.append(f"{car.car_id}: MOVE1 finishes after storage deadline")

        _add_row(rows, "MOVE1", car, storage, w, start, move1_dur, midnight)

    rows.sort(key=lambda r: (r["start"], r["worker"], r["type"]))
    return rows, warnings, storage


# ─────────────────────────────────────────────────────────
# PUBLIC ENTRY POINT
# ─────────────────────────────────────────────────────────
def schedule_day(day_str: str) -> dict:
    """
    Run the greedy scheduler for a given date.

    Returns a dict ready for JSON serialization:
        date, tasks, warnings, summary, storage, source
    """
    midnight = datetime.strptime(day_str, "%Y-%m-%d")
    cars, source, skipped = _load_cars(day_str)

    if not cars:
        return {
            "date":     day_str,
            "tasks":    [],
            "warnings": [f"No bookings found for {day_str} (source: {source})"],
            "summary":  {"total_cars": 0, "total_work_min": 0, "n_gull": 0, "n_p3": 0, "skipped": skipped},
            "storage":  None,
            "source":   source,
        }

    tasks, warnings, storage = _greedy_schedule(cars, midnight)

    n_gull       = sum(1 for r in tasks if r["type"] == "MOVE1" and r["storage"] == "Gull")
    n_p3         = sum(1 for r in tasks if r["type"] == "MOVE1" and r["storage"] == "P3")
    total_work   = sum(r["durationMin"] for r in tasks)

    return {
        "date":     day_str,
        "tasks":    tasks,
        "warnings": warnings,
        "summary": {
            "total_cars":     len(cars),
            "total_work_min": round(total_work, 1),
            "total_work_h":   round(total_work / 60, 2),
            "n_gull":         n_gull,
            "n_p3":           n_p3,
            "skipped":        skipped,
            "num_workers":    NUM_WORKERS,
        },
        "storage": storage,
        "source":  source,
    }
