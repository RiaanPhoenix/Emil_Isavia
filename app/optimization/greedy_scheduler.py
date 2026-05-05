# greedy_scheduler.py
# ---------------------------------------------------------
# FIFO Greedy Scheduler með backhaul
# Supports single-day and multi-day date ranges.
#
# Public interface:
#   schedule_range(date_from, date_to, **kwargs) -> dict
#   schedule_day(day_str, **kwargs)              -> dict  (kept for app.py compat)
#   fifo_schedule(cars, d1g, d1p, d2g, d2p, midnight) -> (rows, warnings)
# ---------------------------------------------------------

import base64
import json
import os
import urllib.request
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

try:
    from config import settings as _settings
    _WALK_GULL       = _settings.WALK_GULL_TO_RECEPTION
    _WALK_P3         = _settings.WALK_P3_TO_RECEPTION
    _WALK_SKIL       = _settings.WALK_DELIVERY_TO_GULL
    _DRIVE_MOTT_GULL = _settings.TRAVEL_RECEPTION_TO_GULL
    _DRIVE_MOTT_P3   = _settings.TRAVEL_RECEPTION_TO_P3
    _DRIVE_GULL_SKIL = _settings.TRAVEL_GULL_TO_DELIVERY
    _DRIVE_P3_SKIL   = _settings.TRAVEL_P3_TO_DELIVERY
except Exception:
    # Fallback defaults (minutes)
    _WALK_GULL = 3.0;  _WALK_P3 = 5.0;  _WALK_SKIL = 4.0
    _DRIVE_MOTT_GULL = 6.0;  _DRIVE_MOTT_P3 = 8.0
    _DRIVE_GULL_SKIL = 5.0;  _DRIVE_P3_SKIL = 7.0

# ─────────────────────────────────────────────────────────
# STILLINGAR
# ─────────────────────────────────────────────────────────
NUM_WORKERS       = 2
PROCESS_MIN       = 1.5   # key-box handling time at reception
RETURN_BUFFER_MIN = 90    # car must be at Skilastæði this many min before arrival
DROPOFF_BEFORE_H  = 3     # customer drops car off this many hours before departure
BACKHAUL_WINDOW_H = 4     # worker will take a return trip if due within this window

CAP_MOTT = 14
CAP_GULL = 50
CAP_P3   = 150
CAP_SKIL = 20

LOC_OFFICE = "Office"
LOC_MOTT   = "Móttökustæði"   # reception / drop-off spot
LOC_GULL   = "Gull"           # storage zone Gull
LOC_P3     = "P3"             # storage zone P3
LOC_SKIL   = "Skilastæði"     # arrival / pick-up spot

API_URL      = os.getenv("PARKING_API_URL",      os.getenv("API_URL",      "https://parking-api-dev-d8b2ejb0asc0gbec.northeurope-01.azurewebsites.net"))
API_USER     = os.getenv("PARKING_API_USERNAME",  os.getenv("API_USER",     ""))
API_PASSWORD = os.getenv("PARKING_API_PASSWORD",  os.getenv("API_PASSWORD", ""))


# ─────────────────────────────────────────────────────────
# CAR — one valet booking
# ─────────────────────────────────────────────────────────
class Car:
    """
    Represents one valet booking.

    Key deadlines:
      dropoff      — when the customer leaves the car at Móttökustæði
                     (= dep_flight − DROPOFF_BEFORE_H)
      storage_ddl  — latest time car must be driven to storage
                     (end of the departure day, 23:59)
      return_ddl   — latest time car must be at Skilastæði
                     (= arr_flight − RETURN_BUFFER_MIN)
    """
    def __init__(self, car_id: str, dep: datetime, arr: datetime):
        self.car_id      = car_id
        self.dep_flight  = dep                                                    # departure flight time
        self.arr_flight  = arr                                                    # arrival flight time
        self.dropoff     = dep - timedelta(hours=DROPOFF_BEFORE_H)               # MOVE1 release time
        self.storage_ddl = dep.replace(hour=23, minute=59, second=0, microsecond=0)  # MOVE1 deadline
        self.return_ddl  = arr - timedelta(minutes=RETURN_BUFFER_MIN)            # MOVE2 deadline

    def __repr__(self):
        return f"Car({self.car_id})"


# ─────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────
def fmt(t: datetime) -> str:
    return t.strftime("%Y-%m-%d %H:%M")

def to_mins(midnight: datetime, t: datetime) -> float:
    return (t - midnight).total_seconds() / 60.0

def _auth_header() -> str:
    return "Basic " + base64.b64encode(f"{API_USER}:{API_PASSWORD}".encode()).decode()

def _api_get(endpoint: str):
    url = API_URL.rstrip("/") + "/" + endpoint.lstrip("/")
    req = urllib.request.Request(url, headers={"Authorization": _auth_header(), "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))

def _parse_dt(s: str) -> datetime:
    s = str(s).strip().replace("T", " ").split(".")[0].split("+")[0].replace("Z", "").strip()
    for f in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d",
              "%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%Y",
              "%d/%m/%Y %H:%M", "%m/%d/%Y %H:%M"):
        try:
            return datetime.strptime(s, f)
        except ValueError:
            pass
    raise ValueError(f"Get ekki þáttað: {s!r}")


# ─────────────────────────────────────────────────────────
# API — load cars for a date range
# ─────────────────────────────────────────────────────────
def _load_cars_range(date_from: str, date_to: str) -> Tuple[List[Car], str, int]:
    """
    Load all cars whose MOVE1 (drop-off) OR MOVE2 (return) falls within
    [date_from, date_to]. Uses 30-day lookback to catch cars dropped off
    earlier that return within the window.

    Returns (cars, source, skipped).
    """
    ID  = ["carId","car_id","CarId","id","bookingId","licensePlate","plateNumber"]
    DEP = ["departure","departureFlight","dep","departureTime","departureDate","Departure"]
    ARR = ["arrival","arrivalFlight","arr","arrivalTime","arrivalDate","Arrival","returnDate"]

    dt_from  = datetime.strptime(date_from, "%Y-%m-%d")
    dt_to    = datetime.strptime(date_to,   "%Y-%m-%d")
    lookback = (dt_from - timedelta(days=30)).strftime("%Y-%m-%d")

    window_start = dt_from.replace(hour=0,  minute=0,  second=0, microsecond=0)
    window_end   = dt_to.replace(  hour=23, minute=59, second=0, microsecond=0)

    def pick(rec, keys):
        for k in keys:
            if k in rec and rec[k] not in (None, ""): return str(rec[k])
        nl = lambda s: s.lower().replace("_","").replace(" ","")
        for k in keys:
            for rk in rec:
                if nl(k) in nl(rk) and rec[rk] not in (None,""): return str(rec[rk])
        return None

    try:
        ep     = f"/premium-bookings?date_start={lookback}&date_end={date_to}"
        result = _api_get(ep)
        raw    = result if isinstance(result, list) else (
            result.get("data") or result.get("bookings") or result.get("reservations") or [])
        source = "api"
    except Exception as e:
        return [], f"api_error: {e}", 0

    cars, skipped = [], 0
    seen = set()
    for rec in raw:
        cid     = pick(rec, ID)
        dep_raw = pick(rec, DEP)
        arr_raw = pick(rec, ARR)
        if not cid or not dep_raw or not arr_raw:
            skipped += 1; continue
        try:
            dep = _parse_dt(dep_raw)
            arr = _parse_dt(arr_raw)
        except ValueError:
            skipped += 1; continue
        if dep > arr: dep, arr = arr, dep
        if cid in seen: continue   # deduplicate
        c = Car(cid, dep, arr)
        # Include if drop-off OR return falls within the window
        if (window_start <= c.dropoff <= window_end) or (window_start <= c.return_ddl <= window_end):
            cars.append(c)
            seen.add(cid)

    return cars, source, skipped


# ─────────────────────────────────────────────────────────
# PARKING TRACKER
# ─────────────────────────────────────────────────────────
class ParkingTracker:
    """Tracks how many cars are in each zone at any point in time (minutes from epoch)."""

    def __init__(self):
        self.slots: Dict[str, List[Tuple[float, float]]] = {
            LOC_MOTT: [], LOC_GULL: [], LOC_P3: [], LOC_SKIL: [],
        }
        self.caps = {
            LOC_MOTT: CAP_MOTT, LOC_GULL: CAP_GULL,
            LOC_P3:   CAP_P3,   LOC_SKIL: CAP_SKIL,
        }

    def count_at(self, loc: str, t: float) -> int:
        return sum(1 for inn, ut in self.slots[loc] if inn <= t < ut)

    def is_full(self, loc: str, t: float) -> bool:
        return self.count_at(loc, t) >= self.caps[loc]

    def add(self, loc: str, inn: float, ut: float):
        self.slots[loc].append((inn, ut))


# ─────────────────────────────────────────────────────────
# BACKHAUL — find a return trip for a worker already at storage
# ─────────────────────────────────────────────────────────
def find_backhaul(car_id_done: str,
                  loc_storage: str,
                  worker_arrives: float,
                  cars_in_storage: Dict,
                  parking: ParkingTracker,
                  d2g: Dict, d2p: Dict) -> Optional[str]:
    """
    After a worker drops off a car in storage, check if there is another
    car already in that same storage zone whose MOVE2 is due within
    BACKHAUL_WINDOW_H hours. If so, return its car_id so the worker
    can drive it to Skilastæði instead of walking back empty.

    Picks the car whose return_ddl is soonest (most urgent).
    """
    window_mins = BACKHAUL_WINDOW_H * 60
    best_cid  = None
    best_rddl = float("inf")

    for cid, info in cars_in_storage.items():
        if cid == car_id_done:               continue
        if info["storage"] != loc_storage:   continue
        if info.get("move2_scheduled"):      continue
        if info["storage_inn"] > worker_arrives: continue  # not parked yet

        rddl           = info["rddl"]
        time_until_ddl = rddl - worker_arrives

        if 0 <= time_until_ddl <= window_mins:
            if rddl < best_rddl:
                best_rddl = rddl
                best_cid  = cid

    return best_cid


# ─────────────────────────────────────────────────────────
# CORE SCHEDULER
# ─────────────────────────────────────────────────────────
def fifo_schedule(cars: list,
                  d1g: Dict, d1p: Dict,
                  d2g: Dict, d2p: Dict,
                  midnight: datetime) -> Tuple[list, list]:
    """
    FIFO Greedy Scheduler for one day.

    Logic:
      1. Sort cars by drop-off time (FIFO).
      2. For each car, assign the next available worker for MOVE1
         (Móttökustæði → storage).
      3. After arriving at storage, check for a backhaul:
         if another car there is due for MOVE2 within BACKHAUL_WINDOW_H,
         have the same worker drive it to Skilastæði immediately — saving
         a round-trip walk.
      4. Schedule MOVE2 (storage → Skilastæði) as late as possible
         (just before return_ddl) to keep storage free longer, using
         whichever worker is free soonest.

    All times are in minutes from midnight of the given day.

    Args:
        cars:     list of Car objects relevant to this day
        d1g/d1p:  MOVE1 duration per car_id for Gull / P3 storage
        d2g/d2p:  MOVE2 duration per car_id for Gull / P3 storage
        midnight: datetime at 00:00 of the day being scheduled

    Returns:
        (rows, warnings)
        rows — list of task dicts, one per move
        warnings — list of human-readable warning strings
    """
    sorted_cars     = sorted(cars, key=lambda c: c.dropoff)
    worker_free     = [0.0] * NUM_WORKERS   # minutes from midnight when each worker is next free
    parking         = ParkingTracker()
    cars_in_storage: Dict = {}
    rows:     list = []
    warnings: list = []

    for c in sorted_cars:
        cid  = c.car_id
        # Clamp all times to [0, 1439] minutes within the day
        rel  = max(0.0,    to_mins(midnight, c.dropoff))
        sddl = min(1439.0, to_mins(midnight, c.storage_ddl))
        rddl = min(1439.0, to_mins(midnight, c.return_ddl))

        dur1_g, dur2_g = d1g[cid], d2g[cid]
        dur1_p, dur2_p = d1p[cid], d2p[cid]

        # ── Choose storage zone ────────────────────────────
        wk1_test = min(range(NUM_WORKERS), key=lambda k: max(worker_free[k], rel))
        s1m_test = max(worker_free[wk1_test], rel)

        gull_free = not parking.is_full(LOC_GULL, s1m_test + dur1_g / 2)
        p3_free   = not parking.is_full(LOC_P3,   s1m_test + dur1_p / 2)

        if gull_free:
            storage, dur1, dur2 = "Gull", dur1_g, dur2_g
            loc_storage = LOC_GULL
        elif p3_free:
            storage, dur1, dur2 = "P3", dur1_p, dur2_p
            loc_storage = LOC_P3
            warnings.append(f"  ⚠ {cid}: Gull fullt → P3")
        else:
            storage, dur1, dur2 = "Gull", dur1_g, dur2_g
            loc_storage = LOC_GULL
            warnings.append(f"  ⚠ {cid}: Gull og P3 full — bíður")

        lbl1 = f"{LOC_MOTT} → {loc_storage}"
        lbl2 = f"{loc_storage} → {LOC_SKIL}"

        # ── MOVE1: Móttökustæði → storage ─────────────────
        wk1 = min(range(NUM_WORKERS), key=lambda k: max(worker_free[k], rel))
        s1m = max(worker_free[wk1], rel)
        # Pin end to storage deadline; back-calculate start
        e1m = min(s1m + dur1, sddl)
        s1m = e1m - dur1
        worker_free[wk1] = e1m

        parking.add(LOC_MOTT, rel, s1m)
        storage_inn = e1m   # time car arrives in storage

        cars_in_storage[cid] = {
            "storage":         loc_storage,
            "storage_inn":     storage_inn,
            "rddl":            rddl,
            "dur2":            dur2,
            "car":             c,
            "move2_scheduled": False,
        }

        # ── BACKHAUL: worker drives another car to Skilastæði on the way back ──
        bh_cid = find_backhaul(
            car_id_done     = cid,
            loc_storage     = loc_storage,
            worker_arrives  = e1m,
            cars_in_storage = cars_in_storage,
            parking         = parking,
            d2g             = d2g,
            d2p             = d2p,
        )

        if bh_cid:
            bh      = cars_in_storage[bh_cid]
            bh_car  = bh["car"]
            bh_dur2 = bh["dur2"]
            bh_rddl = bh["rddl"]
            bh_stor = bh["storage"]
            bh_lbl2 = f"{bh_stor} → {LOC_SKIL}"

            # Start backhaul immediately; if that breaches deadline, pull forward
            bh_s2m = e1m
            bh_e2m = bh_s2m + bh_dur2
            if bh_e2m > bh_rddl:
                bh_s2m = max(bh["storage_inn"], bh_rddl - bh_dur2)
                bh_e2m = bh_s2m + bh_dur2

            worker_free[wk1] = bh_e2m
            bh_t2s = midnight + timedelta(minutes=bh_s2m)

            rows.append({
                "type":             "MOVE2",
                "carId":            bh_cid,
                "storage":          bh_stor,
                "worker":           f"W{wk1 + 1}",
                "movingMin":        round(bh_dur2, 1),
                "move":             bh_lbl2,
                "moveStart":        fmt(bh_t2s),
                "moveEnd":          fmt(bh_t2s + timedelta(minutes=bh_dur2)),
                "dropoffTime":      fmt(bh_car.dropoff),
                "depFlight":        fmt(bh_car.dep_flight),
                "arrFlight":        fmt(bh_car.arr_flight),
                "arrReadyBy":       fmt(bh_car.return_ddl),
                "storageDeadline":  fmt(bh_car.storage_ddl),
                "note":             f"BACKHAUL eftir Move1 á {cid}",
            })

            parking.add(bh_stor, bh["storage_inn"], bh_s2m)
            parking.add(LOC_SKIL, bh_e2m, bh_e2m + 60)
            cars_in_storage[bh_cid]["move2_scheduled"] = True
            warnings.append(
                f"  ✓ BACKHAUL: W{wk1+1} skilar {bh_cid} "
                f"á leiðinni eftir Move1 á {cid}"
            )

        # ── MOVE2: storage → Skilastæði ───────────────────
        # Schedule as late as possible (just before return_ddl)
        ideal_s2m   = rddl - dur2
        earliest_m2 = e1m          # can't start before MOVE1 finishes
        s2m = max(earliest_m2, ideal_s2m)
        e2m = s2m + dur2

        # Back off if Skilastæði is full
        attempts = 0
        while parking.is_full(LOC_SKIL, s2m + dur2 / 2) and s2m > earliest_m2:
            s2m = max(earliest_m2, s2m - 10)
            e2m = s2m + dur2
            attempts += 1
            if attempts > 100: break

        if parking.is_full(LOC_SKIL, s2m + dur2 / 2):
            warnings.append(f"  ⚠ {cid}: Skilastæði fullt")

        # Assign worker (freest one that is available by earliest_m2)
        wk2       = min(range(NUM_WORKERS), key=lambda k: max(worker_free[k], earliest_m2))
        wk2_start = max(worker_free[wk2], s2m)
        if wk2_start > s2m:
            s2m = wk2_start
            e2m = s2m + dur2
        worker_free[wk2] = e2m

        parking.add(loc_storage, storage_inn, s2m)
        parking.add(LOC_SKIL, e2m, e2m + 60)

        t1s = midnight + timedelta(minutes=s1m)
        t2s = midnight + timedelta(minutes=s2m)

        if e2m > rddl:
            warnings.append(f"  ⚠ {cid}: Move2 {e2m - rddl:.0f} mín of seint!")

        cars_in_storage[cid]["move2_scheduled"] = True

        rows.append({
            "type":             "MOVE1",
            "carId":            cid,
            "storage":          storage,
            "worker":           f"W{wk1 + 1}",
            "movingMin":        round(dur1, 1),
            "move":             lbl1,
            "moveStart":        fmt(t1s),
            "moveEnd":          fmt(t1s + timedelta(minutes=dur1)),
            "dropoffTime":      fmt(c.dropoff),
            "depFlight":        fmt(c.dep_flight),
            "arrFlight":        fmt(c.arr_flight),
            "arrReadyBy":       fmt(c.return_ddl),
            "storageDeadline":  fmt(c.storage_ddl),
            "note":             "",
        })
        rows.append({
            "type":             "MOVE2",
            "carId":            cid,
            "storage":          storage,
            "worker":           f"W{wk2 + 1}",
            "movingMin":        round(dur2, 1),
            "move":             lbl2,
            "moveStart":        fmt(t2s),
            "moveEnd":          fmt(t2s + timedelta(minutes=dur2)),
            "dropoffTime":      fmt(c.dropoff),
            "depFlight":        fmt(c.dep_flight),
            "arrFlight":        fmt(c.arr_flight),
            "arrReadyBy":       fmt(c.return_ddl),
            "storageDeadline":  fmt(c.storage_ddl),
            "note":             "",
        })

    return rows, warnings


# ─────────────────────────────────────────────────────────
# DURATION HELPERS
# ─────────────────────────────────────────────────────────
def _build_dur_dicts(cars: List[Car]):
    """Build per-car duration dicts for fifo_schedule from settings travel times."""
    dur1_gull = _WALK_GULL + PROCESS_MIN + _DRIVE_MOTT_GULL
    dur1_p3   = _WALK_P3   + PROCESS_MIN + _DRIVE_MOTT_P3
    dur2_gull = _DRIVE_GULL_SKIL + _WALK_SKIL
    dur2_p3   = _DRIVE_P3_SKIL   + _WALK_SKIL
    d1g = {c.car_id: dur1_gull for c in cars}
    d1p = {c.car_id: dur1_p3   for c in cars}
    d2g = {c.car_id: dur2_gull for c in cars}
    d2p = {c.car_id: dur2_p3   for c in cars}
    return d1g, d1p, d2g, d2p


# ─────────────────────────────────────────────────────────
# PUBLIC: schedule_range — multi-day entry point
# ─────────────────────────────────────────────────────────
def schedule_range(
    date_from: str,
    date_to: str,
    day_movers: int = 2,
    night_workers: int = 2,
    supervisor: bool = True,
    move2_window: int = 60,
) -> dict:
    """
    Schedule all valet movements for a date range.

    Loads all cars whose drop-off or return falls within [date_from, date_to],
    then runs fifo_schedule once per day within the range.

    Returns a dict with:
      date_from, date_to, days (list of per-day results), summary (aggregate)
    """
    dt_from = datetime.strptime(date_from, "%Y-%m-%d")
    dt_to   = datetime.strptime(date_to,   "%Y-%m-%d")

    if dt_to < dt_from:
        dt_from, dt_to = dt_to, dt_from

    all_cars, source, skipped = _load_cars_range(date_from, date_to)

    days_out      = []
    total_tasks   = []
    total_warnings = []
    total_cars_seen = set()

    current = dt_from
    while current <= dt_to:
        day_str  = current.strftime("%Y-%m-%d")
        midnight = current

        day0 = current.replace(hour=0,  minute=0,  second=0, microsecond=0)
        day1 = current.replace(hour=23, minute=59, second=0, microsecond=0)

        # Cars whose MOVE1 or MOVE2 falls on this day
        day_cars = [
            c for c in all_cars
            if (day0 <= c.dropoff <= day1) or (day0 <= c.return_ddl <= day1)
        ]

        if day_cars:
            d1g, d1p, d2g, d2p = _build_dur_dicts(day_cars)
            tasks, warnings = fifo_schedule(day_cars, d1g, d1p, d2g, d2p, midnight)
        else:
            tasks, warnings = [], []

        n_gull = sum(1 for r in tasks if r["type"] == "MOVE1" and r["storage"] == "Gull")
        n_p3   = sum(1 for r in tasks if r["type"] == "MOVE1" and r["storage"] == "P3")
        n_bh   = sum(1 for r in tasks if "BACKHAUL" in r.get("note", ""))
        work   = sum(r["movingMin"] for r in tasks)

        day_result = {
            "date":     day_str,
            "tasks":    tasks,
            "warnings": warnings,
            "summary": {
                "total_cars":     len(day_cars),
                "n_gull":         n_gull,
                "n_p3":           n_p3,
                "n_backhaul":     n_bh,
                "total_work_min": round(work, 1),
                "total_work_h":   round(work / 60, 2),
            },
        }
        days_out.append(day_result)
        total_tasks.extend(tasks)
        total_warnings.extend(warnings)
        total_cars_seen.update(c.car_id for c in day_cars)

        current += timedelta(days=1)

    total_work = sum(r["movingMin"] for r in total_tasks)
    n_days     = (dt_to - dt_from).days + 1

    return {
        "date_from":  date_from,
        "date_to":    date_to,
        "n_days":     n_days,
        "source":     source,
        "days":       days_out,
        "all_tasks":  total_tasks,
        "warnings":   total_warnings,
        "summary": {
            "total_cars":      len(total_cars_seen),
            "total_tasks":     len(total_tasks),
            "total_work_min":  round(total_work, 1),
            "total_work_h":    round(total_work / 60, 2),
            "skipped":         skipped,
            "day_movers":      day_movers,
            "night_workers":   night_workers,
            "supervisor":      supervisor,
        },
    }


# ─────────────────────────────────────────────────────────
# PUBLIC: schedule_day — single-day entry point (app.py compat)
# ─────────────────────────────────────────────────────────
def schedule_day(
    day_str: str,
    day_movers: int = 2,
    night_workers: int = 2,
    supervisor: bool = True,
    move2_window: int = 60,
) -> dict:
    """Single-day wrapper around schedule_range. Kept for app.py compatibility."""
    result = schedule_range(day_str, day_str, day_movers, night_workers, supervisor, move2_window)

    # Flatten to the shape app.py expects
    day = result["days"][0] if result["days"] else {"tasks": [], "warnings": [], "summary": {}}
    return {
        "date":     day_str,
        "tasks":    day["tasks"],
        "warnings": day["warnings"],
        "summary":  day["summary"],
        "source":   result["source"],
    }
