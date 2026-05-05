# greedy_scheduler.py
# ---------------------------------------------------------
# FIFO Greedy Scheduler — multi-day date range support
#
# Public interface:
#   schedule_range(date_from, date_to, **kwargs) -> dict
#   schedule_day(day_str, **kwargs)              -> dict  (compat shim)
#   fifo_schedule(...)                           -> (rows, warnings)
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
    _WALK_GULL = 3.0;  _WALK_P3 = 5.0;  _WALK_SKIL = 4.0
    _DRIVE_MOTT_GULL = 6.0;  _DRIVE_MOTT_P3 = 8.0
    _DRIVE_GULL_SKIL = 5.0;  _DRIVE_P3_SKIL = 7.0

# ─────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────
NUM_WORKERS       = 2
PROCESS_MIN       = 1.5    # key-box handling at reception
RETURN_BUFFER_MIN = 90     # car must reach Skilastæði this many min before arrival flight
DROPOFF_BEFORE_H  = 3      # customer drops car off N hours before departure flight
BACKHAUL_WINDOW_H = 4      # only attempt backhaul if MOVE2 due within this many hours

CAP_MOTT = 14
CAP_GULL = 50
CAP_P3   = 150
CAP_SKIL = 14   # only 14 free spots in arrival zone — hard limit

LOC_OFFICE = "Office"
LOC_MOTT   = "Móttökustæði"
LOC_GULL   = "Gull"
LOC_P3     = "P3"
LOC_SKIL   = "Skilastæði"

API_URL      = os.getenv("PARKING_API_URL",     os.getenv("API_URL",      "https://parking-api-dev-d8b2ejb0asc0gbec.northeurope-01.azurewebsites.net"))
API_USER     = os.getenv("PARKING_API_USERNAME", os.getenv("API_USER",    ""))
API_PASSWORD = os.getenv("PARKING_API_PASSWORD", os.getenv("API_PASSWORD",""))


# ─────────────────────────────────────────────────────────
# CAR
# ─────────────────────────────────────────────────────────
class Car:
    """
    One valet booking with two scheduled worker moves:

    MOVE1  Móttökustæði → storage
           Triggered on the day of departure (customer drop-off).
           release time : dropoff   = dep_flight − DROPOFF_BEFORE_H
           deadline     : storage_ddl = end of departure day (23:59)

    MOVE2  storage → Skilastæði
           Triggered on the day of arrival (customer lands back).
           deadline     : return_ddl = arr_flight − RETURN_BUFFER_MIN
    """
    def __init__(self, car_id: str, dep: datetime, arr: datetime):
        self.car_id      = car_id
        self.dep_flight  = dep
        self.arr_flight  = arr
        self.dropoff     = dep - timedelta(hours=DROPOFF_BEFORE_H)
        self.storage_ddl = dep.replace(hour=23, minute=59, second=0, microsecond=0)
        self.return_ddl  = arr - timedelta(minutes=RETURN_BUFFER_MIN)

    def __repr__(self):
        return f"Car({self.car_id})"


# ─────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────
def fmt(t: datetime) -> str:
    return t.strftime("%Y-%m-%d %H:%M")

def to_mins(ref: datetime, t: datetime) -> float:
    """Minutes from ref to t (can be negative for past events)."""
    return (t - ref).total_seconds() / 60.0

def _auth_header() -> str:
    return "Basic " + base64.b64encode(f"{API_USER}:{API_PASSWORD}".encode()).decode()

def _api_get(endpoint: str):
    url = API_URL.rstrip("/") + "/" + endpoint.lstrip("/")
    req = urllib.request.Request(url, headers={"Authorization": _auth_header(), "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))

def _parse_dt(s: str) -> datetime:
    s = str(s).strip().replace("T"," ").split(".")[0].split("+")[0].replace("Z","").strip()
    for f in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d",
              "%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%Y",
              "%d/%m/%Y %H:%M", "%m/%d/%Y %H:%M"):
        try: return datetime.strptime(s, f)
        except ValueError: pass
    raise ValueError(f"Cannot parse: {s!r}")

def _day_start(d: datetime) -> datetime:
    return d.replace(hour=0, minute=0, second=0, microsecond=0)

def _day_end(d: datetime) -> datetime:
    return d.replace(hour=23, minute=59, second=59, microsecond=0)


# ─────────────────────────────────────────────────────────
# API — load cars for a date range
# ─────────────────────────────────────────────────────────
def _load_cars_range(date_from: str, date_to: str) -> Tuple[List[Car], str, int]:
    """
    Load all cars that need worker action within [date_from, date_to]:
      - MOVE1 cars: drop-off day falls in range
      - MOVE2 cars: return deadline day falls in range
      (A car whose dep was 2 weeks ago but returns today is MOVE2-only.)

    Uses 60-day lookback to catch long-stay cars.
    Returns (cars, source, skipped).
    """
    ID  = ["carId","car_id","CarId","id","bookingId","licensePlate","plateNumber"]
    DEP = ["departure","departureFlight","dep","departureTime","departureDate","Departure"]
    ARR = ["arrival","arrivalFlight","arr","arrivalTime","arrivalDate","Arrival","returnDate"]

    dt_from  = datetime.strptime(date_from, "%Y-%m-%d")
    dt_to    = datetime.strptime(date_to,   "%Y-%m-%d")
    lookback = (dt_from - timedelta(days=60)).strftime("%Y-%m-%d")

    win_start = _day_start(dt_from)
    win_end   = _day_end(dt_to)

    def pick(rec, keys):
        for k in keys:
            if k in rec and rec[k] not in (None,""): return str(rec[k])
        nl = lambda s: s.lower().replace("_","").replace(" ","")
        for k in keys:
            for rk in rec:
                if nl(k) in nl(rk) and rec[rk] not in (None,""): return str(rec[rk])
        return None

    try:
        ep     = f"/premium-bookings?date_start={lookback}&date_end={date_to}"
        result = _api_get(ep)
        raw    = result if isinstance(result, list) else (
                 result.get("data") or result.get("bookings") or
                 result.get("reservations") or [])
        source = "api"
    except Exception as e:
        return [], f"api_error: {e}", 0

    cars, skipped, seen = [], 0, set()
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
        if cid in seen: continue
        c = Car(cid, dep, arr)
        # Include if MOVE1 day OR MOVE2 day falls in the window
        move1_day = _day_start(c.dropoff)
        move2_day = _day_start(c.return_ddl)
        if (win_start <= move1_day <= win_end) or (win_start <= move2_day <= win_end):
            cars.append(c)
            seen.add(cid)

    return cars, source, skipped


# ─────────────────────────────────────────────────────────
# PARKING TRACKER
# ─────────────────────────────────────────────────────────
class ParkingTracker:
    """Tracks occupancy per zone in absolute minutes-from-epoch."""

    def __init__(self):
        self.slots: Dict[str, List[Tuple[float, float]]] = {
            LOC_MOTT: [], LOC_GULL: [], LOC_P3: [], LOC_SKIL: [],
        }
        self.caps = {
            LOC_MOTT: CAP_MOTT, LOC_GULL: CAP_GULL,
            LOC_P3:   CAP_P3,   LOC_SKIL: CAP_SKIL,
        }

    def count_at(self, loc: str, t: float) -> int:
        return sum(1 for a, b in self.slots[loc] if a <= t < b)

    def is_full(self, loc: str, t: float) -> bool:
        return self.count_at(loc, t) >= self.caps[loc]

    def add(self, loc: str, inn: float, ut: float):
        if ut > inn:
            self.slots[loc].append((inn, ut))


# ─────────────────────────────────────────────────────────
# BACKHAUL — find a valid return trip
# ─────────────────────────────────────────────────────────
def find_backhaul(
    car_id_done: str,
    loc_storage: str,
    worker_arrives_abs: float,      # absolute minutes from epoch
    cars_in_storage: Dict,
    parking: ParkingTracker,
) -> Tuple[Optional[str], Optional[str]]:
    """
    After finishing MOVE1, check if the worker can immediately do a
    MOVE2 for another car already in the same storage zone.

    Rules:
      1. The candidate car must already be in storage (storage_inn <= now).
      2. Its return_ddl must be within BACKHAUL_WINDOW_H from now
         (urgent enough to justify the trip).
      3. The return_ddl must not have already passed.
      4. There must be a free spot in Skilastæði at the time of arrival.
      5. MOVE2 must not already be scheduled for that car.

    Returns (car_id, None) if a valid backhaul is found, else (None, reason).
    reason is a short string explaining why no backhaul was assigned.
    """
    window_mins = BACKHAUL_WINDOW_H * 60
    best_cid  = None
    best_rddl = float("inf")

    no_candidate  = True
    wrong_zone    = True
    all_scheduled = True
    not_in_yet    = True
    not_urgent    = True
    skil_full_flag = False

    for cid, info in cars_in_storage.items():
        if cid == car_id_done: continue
        no_candidate = False

        if info["storage"] != loc_storage:
            continue
        wrong_zone = False

        if info.get("move2_scheduled"):
            continue
        all_scheduled = False

        if info["storage_inn"] > worker_arrives_abs:
            continue
        not_in_yet = False

        rddl           = info["rddl_abs"]
        time_until_ddl = rddl - worker_arrives_abs

        if time_until_ddl < 0:
            # Already past deadline — skip
            continue
        if time_until_ddl > window_mins:
            not_urgent = False  # not urgent enough yet — not an error
            continue
        not_urgent = False

        # Check Skilastæði capacity at estimated arrival time
        dur2        = info["dur2"]
        est_arrival = worker_arrives_abs + dur2
        if parking.is_full(LOC_SKIL, est_arrival):
            skil_full_flag = True
            continue

        if rddl < best_rddl:
            best_rddl = rddl
            best_cid  = cid

    if best_cid:
        return best_cid, None

    # Build a human-readable reason
    if no_candidate or wrong_zone:
        reason = "no other car in same storage zone"
    elif all_scheduled:
        reason = "all zone cars already scheduled for return"
    elif not_in_yet:
        reason = "no car has arrived in storage yet"
    elif skil_full_flag:
        reason = f"arrival zone full ({CAP_SKIL} spots)"
    elif not not_urgent:
        reason = "no return due within optimization window"
    else:
        reason = "no valid return move available"

    return None, reason


# ─────────────────────────────────────────────────────────
# PER-DAY SCHEDULER
# ─────────────────────────────────────────────────────────
def fifo_schedule(
    move1_cars: List[Car],   # cars whose MOVE1 (drop-off → storage) is today
    move2_cars: List[Car],   # cars whose MOVE2 (storage → arrival) is today
    storage_pool: Dict,      # cars already in storage from prior days: {car_id: info}
    d1g: Dict, d1p: Dict,
    d2g: Dict, d2p: Dict,
    day_start_abs: float,    # absolute minutes (epoch-based) at 00:00 of this day
    day_end_abs:   float,    # absolute minutes at 23:59 of this day
    parking: ParkingTracker,
) -> Tuple[list, list]:
    """
    Schedule all moves for one calendar day.

    MOVE1 cars are sorted by drop-off time (FIFO).
    After each MOVE1, the worker checks for a valid backhaul (MOVE2).
    MOVE2-only cars (returned from long trips) are also scheduled.

    All times in absolute minutes from a shared epoch (minutes since
    2000-01-01 00:00 UTC, for example). Using absolute times means
    a car dropped off two weeks ago has storage_inn in the past —
    MOVE1 is already done and only MOVE2 needs scheduling today.

    Returns (rows, warnings).
    """
    rows: list     = []
    warnings: list = []

    # Worker free times in absolute minutes
    worker_free = [day_start_abs] * NUM_WORKERS

    # cars_in_storage tracks cars currently in storage (for backhaul lookup)
    # Seeded from prior-day storage pool
    cars_in_storage: Dict = dict(storage_pool)

    # ── MOVE1 pass: drop-off → storage ─────────────────
    sorted_m1 = sorted(move1_cars, key=lambda c: c.dropoff)

    for c in sorted_m1:
        cid      = c.car_id
        dur1_g   = d1g[cid]
        dur1_p   = d1p[cid]
        dur2_g   = d2g[cid]
        dur2_p   = d2p[cid]

        # Release time: when car arrives at Móttökustæði
        rel_abs  = day_start_abs + to_mins(
            datetime.utcfromtimestamp(day_start_abs * 60) if False else
            datetime(1, 1, 1) + timedelta(minutes=day_start_abs),
            c.dropoff
        )
        # Simpler: absolute minutes of dropoff
        rel_abs  = _dt_to_abs(c.dropoff)
        sddl_abs = _dt_to_abs(c.storage_ddl)
        rddl_abs = _dt_to_abs(c.return_ddl)

        # Clamp release to today (can't start before day begins)
        rel_abs  = max(rel_abs, day_start_abs)
        sddl_abs = min(sddl_abs, day_end_abs)

        # Choose storage zone
        wk1_test = min(range(NUM_WORKERS), key=lambda k: max(worker_free[k], rel_abs))
        s1_test  = max(worker_free[wk1_test], rel_abs)

        gull_ok = not parking.is_full(LOC_GULL, s1_test + dur1_g / 2)
        p3_ok   = not parking.is_full(LOC_P3,   s1_test + dur1_p / 2)

        if gull_ok:
            storage, dur1, dur2 = "Gull", dur1_g, dur2_g
            loc_storage = LOC_GULL
        elif p3_ok:
            storage, dur1, dur2 = "P3", dur1_p, dur2_p
            loc_storage = LOC_P3
            warnings.append(f"  ⚠ {cid}: Gull fullt → P3")
        else:
            storage, dur1, dur2 = "Gull", dur1_g, dur2_g
            loc_storage = LOC_GULL
            warnings.append(f"  ⚠ {cid}: Gull og P3 full — bíður")

        lbl1 = f"{LOC_MOTT} → {loc_storage}"

        # Assign MOVE1 worker
        wk1     = min(range(NUM_WORKERS), key=lambda k: max(worker_free[k], rel_abs))
        s1_abs  = max(worker_free[wk1], rel_abs)
        e1_abs  = min(s1_abs + dur1, sddl_abs)
        s1_abs  = e1_abs - dur1   # back-calculate start from deadline
        worker_free[wk1] = e1_abs

        parking.add(LOC_MOTT, rel_abs, s1_abs)

        # Register car in storage
        cars_in_storage[cid] = {
            "storage":         loc_storage,
            "storage_inn":     e1_abs,
            "rddl_abs":        rddl_abs,
            "dur2":            dur2,
            "car":             c,
            "move2_scheduled": False,
        }

        rows.append({
            "type":            "MOVE1",
            "carId":           cid,
            "storage":         storage,
            "worker":          f"W{wk1+1}",
            "movingMin":       round(dur1, 1),
            "move":            lbl1,
            "moveStart":       fmt(_abs_to_dt(s1_abs)),
            "moveEnd":         fmt(_abs_to_dt(e1_abs)),
            "dropoffTime":     fmt(c.dropoff),
            "depFlight":       fmt(c.dep_flight),
            "arrFlight":       fmt(c.arr_flight),
            "arrReadyBy":      fmt(c.return_ddl),
            "storageDeadline": fmt(c.storage_ddl),
            "note":            "",
            "noReturnReason":  "",
        })

        # ── Backhaul check ───────────────────────────────
        bh_cid, bh_reason = find_backhaul(
            car_id_done        = cid,
            loc_storage        = loc_storage,
            worker_arrives_abs = e1_abs,
            cars_in_storage    = cars_in_storage,
            parking            = parking,
        )

        if bh_cid:
            bh      = cars_in_storage[bh_cid]
            bh_car  = bh["car"]
            bh_dur2 = bh["dur2"]
            bh_rddl = bh["rddl_abs"]
            bh_stor = bh["storage"]

            # Start immediately; pull back if it would breach deadline
            bh_s = e1_abs
            bh_e = bh_s + bh_dur2
            if bh_e > bh_rddl:
                bh_s = max(bh["storage_inn"], bh_rddl - bh_dur2)
                bh_e = bh_s + bh_dur2

            worker_free[wk1] = bh_e
            parking.add(bh_stor, bh["storage_inn"], bh_s)
            parking.add(LOC_SKIL, bh_e, bh_e + 60)
            cars_in_storage[bh_cid]["move2_scheduled"] = True

            rows.append({
                "type":            "MOVE2",
                "carId":           bh_cid,
                "storage":         bh_stor,
                "worker":          f"W{wk1+1}",
                "movingMin":       round(bh_dur2, 1),
                "move":            f"{bh_stor} → {LOC_SKIL}",
                "moveStart":       fmt(_abs_to_dt(bh_s)),
                "moveEnd":         fmt(_abs_to_dt(bh_e)),
                "dropoffTime":     fmt(bh_car.dropoff),
                "depFlight":       fmt(bh_car.dep_flight),
                "arrFlight":       fmt(bh_car.arr_flight),
                "arrReadyBy":      fmt(bh_car.return_ddl),
                "storageDeadline": fmt(bh_car.storage_ddl),
                "note":            f"BACKHAUL after MOVE1 for {cid}",
                "noReturnReason":  "",
            })
            warnings.append(
                f"  ✓ BACKHAUL: W{wk1+1} returns {bh_cid} after storing {cid}"
            )
        else:
            # Record why no return was made — shown in UI
            rows[-1]["noReturnReason"] = bh_reason or ""

    # ── MOVE2 pass: storage → arrival (for cars due today) ─
    # Includes both backhaul-eligible and standalone returns
    for c in sorted(move2_cars, key=lambda c: c.return_ddl):
        cid = c.car_id

        info = cars_in_storage.get(cid)
        if info and info.get("move2_scheduled"):
            continue   # already done via backhaul

        rddl_abs = _dt_to_abs(c.return_ddl)
        # Only act if return is today
        if rddl_abs < day_start_abs or rddl_abs > day_end_abs:
            continue

        # Determine storage zone (from pool or default)
        if info:
            loc_storage = info["storage"]
            stor_inn    = info["storage_inn"]
            dur2 = d2g[cid] if loc_storage == LOC_GULL else d2p[cid]
        else:
            # Car was stored on a prior day — assume Gull unless P3 was noted
            loc_storage = LOC_GULL
            stor_inn    = day_start_abs    # treat as available all day
            dur2 = d2g[cid]

        storage = "Gull" if loc_storage == LOC_GULL else "P3"

        # Check capacity
        earliest_m2 = max(stor_inn, day_start_abs)
        ideal_s2    = rddl_abs - dur2
        s2_abs      = max(earliest_m2, ideal_s2)
        e2_abs      = s2_abs + dur2

        # Back off if arrival zone is full
        attempts = 0
        while parking.is_full(LOC_SKIL, s2_abs + dur2 / 2) and s2_abs > earliest_m2:
            s2_abs = max(earliest_m2, s2_abs - 10)
            e2_abs = s2_abs + dur2
            attempts += 1
            if attempts > 100: break

        if parking.is_full(LOC_SKIL, s2_abs + dur2 / 2):
            warnings.append(f"  ⚠ {cid}: Skilastæði full — cannot schedule MOVE2")
            continue

        wk2       = min(range(NUM_WORKERS), key=lambda k: max(worker_free[k], earliest_m2))
        wk2_start = max(worker_free[wk2], s2_abs)
        if wk2_start > s2_abs:
            s2_abs = wk2_start
            e2_abs = s2_abs + dur2
        worker_free[wk2] = e2_abs

        parking.add(loc_storage, stor_inn, s2_abs)
        parking.add(LOC_SKIL, e2_abs, e2_abs + 60)

        if e2_abs > rddl_abs:
            warnings.append(f"  ⚠ {cid}: MOVE2 finishes {e2_abs - rddl_abs:.0f} min late!")

        if info:
            cars_in_storage[cid]["move2_scheduled"] = True

        rows.append({
            "type":            "MOVE2",
            "carId":           cid,
            "storage":         storage,
            "worker":          f"W{wk2+1}",
            "movingMin":       round(dur2, 1),
            "move":            f"{loc_storage} → {LOC_SKIL}",
            "moveStart":       fmt(_abs_to_dt(s2_abs)),
            "moveEnd":         fmt(_abs_to_dt(e2_abs)),
            "dropoffTime":     fmt(c.dropoff),
            "depFlight":       fmt(c.dep_flight),
            "arrFlight":       fmt(c.arr_flight),
            "arrReadyBy":      fmt(c.return_ddl),
            "storageDeadline": fmt(c.storage_ddl),
            "note":            "",
            "noReturnReason":  "",
        })

    return rows, warnings


# ─────────────────────────────────────────────────────────
# ABSOLUTE TIME HELPERS
# Using minutes since 2000-01-01 00:00:00 as epoch
# ─────────────────────────────────────────────────────────
_EPOCH = datetime(2000, 1, 1, 0, 0, 0)

def _dt_to_abs(dt: datetime) -> float:
    return (dt - _EPOCH).total_seconds() / 60.0

def _abs_to_dt(abs_min: float) -> datetime:
    return _EPOCH + timedelta(minutes=abs_min)

def _day_abs_start(day_str: str) -> float:
    return _dt_to_abs(datetime.strptime(day_str, "%Y-%m-%d"))

def _day_abs_end(day_str: str) -> float:
    return _dt_to_abs(datetime.strptime(day_str, "%Y-%m-%d").replace(hour=23, minute=59, second=59))


# ─────────────────────────────────────────────────────────
# DURATION HELPERS
# ─────────────────────────────────────────────────────────
def _build_dur_dicts(cars: List[Car]) -> Tuple[Dict, Dict, Dict, Dict]:
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
# PUBLIC: schedule_range
# ─────────────────────────────────────────────────────────
def schedule_range(
    date_from: str,
    date_to:   str,
    day_movers:    int  = 2,
    night_workers: int  = 2,
    supervisor:    bool = True,
    move2_window:  int  = 60,
) -> dict:
    """
    Schedule all valet movements across [date_from, date_to].

    Per day:
      move1_cars — cars whose drop-off (MOVE1) falls on this day
      move2_cars — cars whose return deadline (MOVE2) falls on this day
      storage_pool — cars already in storage from prior days

    The parking tracker is shared across days so capacity is tracked
    correctly across the whole range.
    """
    dt_from = datetime.strptime(date_from, "%Y-%m-%d")
    dt_to   = datetime.strptime(date_to,   "%Y-%m-%d")
    if dt_to < dt_from:
        dt_from, dt_to = dt_to, dt_from

    all_cars, source, skipped = _load_cars_range(
        dt_from.strftime("%Y-%m-%d"),
        dt_to.strftime("%Y-%m-%d"),
    )

    # Shared state across days
    parking      = ParkingTracker()
    storage_pool = {}    # {car_id: storage_info} for cars in storage

    days_out       = []
    all_tasks      = []
    all_warnings   = []
    all_car_ids    = set()

    current = dt_from
    while current <= dt_to:
        day_str = current.strftime("%Y-%m-%d")
        d_start = _day_abs_start(day_str)
        d_end   = _day_abs_end(day_str)

        day0 = _day_start(current)
        day1 = _day_end(current)

        # Cars whose MOVE1 is today
        move1_cars = [c for c in all_cars if day0 <= c.dropoff <= day1]
        # Cars whose MOVE2 is today
        move2_cars = [c for c in all_cars if day0 <= c.return_ddl <= day1]

        # Build duration dicts for all cars relevant today
        relevant = list({c.car_id: c for c in move1_cars + move2_cars}.values())
        if relevant:
            d1g, d1p, d2g, d2p = _build_dur_dicts(relevant)
            # Add any storage-pool cars that are MOVE2-only today
            for cid, info in storage_pool.items():
                if cid not in d1g:
                    car = info["car"]
                    dur1_gull = _WALK_GULL + PROCESS_MIN + _DRIVE_MOTT_GULL
                    dur2_gull = _DRIVE_GULL_SKIL + _WALK_SKIL
                    d1g[cid] = dur1_gull; d1p[cid] = dur1_gull
                    d2g[cid] = dur2_gull; d2p[cid] = dur2_gull
        else:
            d1g = d1p = d2g = d2p = {}

        if move1_cars or move2_cars:
            tasks, warnings = fifo_schedule(
                move1_cars, move2_cars, storage_pool,
                d1g, d1p, d2g, d2p,
                d_start, d_end, parking,
            )
        else:
            tasks, warnings = [], []

        # Update storage pool: add newly stored cars, remove returned ones
        for t in tasks:
            cid = t["carId"]
            if t["type"] == "MOVE1":
                # Find the Car object
                car_obj = next((c for c in all_cars if c.car_id == cid), None)
                if car_obj and cid not in storage_pool:
                    dur2 = d2g.get(cid, _DRIVE_GULL_SKIL + _WALK_SKIL)
                    storage_pool[cid] = {
                        "storage":         t["storage"],
                        "storage_inn":     _dt_to_abs(_parse_dt(t["moveEnd"])),
                        "rddl_abs":        _dt_to_abs(car_obj.return_ddl),
                        "dur2":            dur2,
                        "car":             car_obj,
                        "move2_scheduled": False,
                    }
            elif t["type"] == "MOVE2":
                storage_pool.pop(cid, None)

        n_m1  = sum(1 for t in tasks if t["type"] == "MOVE1")
        n_m2  = sum(1 for t in tasks if t["type"] == "MOVE2")
        n_bh  = sum(1 for t in tasks if "BACKHAUL" in (t.get("note") or ""))
        work  = sum(t["movingMin"] for t in tasks)

        all_car_ids.update(t["carId"] for t in tasks)

        day_result = {
            "date":     day_str,
            "tasks":    tasks,
            "warnings": warnings,
            "summary": {
                "n_move1":        n_m1,
                "n_move2":        n_m2,
                "n_backhaul":     n_bh,
                "total_work_min": round(work, 1),
                "total_work_h":   round(work / 60, 2),
            },
        }
        days_out.append(day_result)
        all_tasks.extend(tasks)
        all_warnings.extend(warnings)

        current += timedelta(days=1)

    total_work = sum(t["movingMin"] for t in all_tasks)
    n_days     = (dt_to - dt_from).days + 1

    return {
        "date_from":  date_from,
        "date_to":    date_to,
        "n_days":     n_days,
        "source":     source,
        "days":       days_out,
        "all_tasks":  all_tasks,
        "warnings":   all_warnings,
        "summary": {
            "total_cars":     len(all_car_ids),
            "total_tasks":    len(all_tasks),
            "n_move1":        sum(1 for t in all_tasks if t["type"] == "MOVE1"),
            "n_move2":        sum(1 for t in all_tasks if t["type"] == "MOVE2"),
            "n_backhaul":     sum(1 for t in all_tasks if "BACKHAUL" in (t.get("note") or "")),
            "total_work_min": round(total_work, 1),
            "total_work_h":   round(total_work / 60, 2),
            "skipped":        skipped,
            "day_movers":     day_movers,
            "night_workers":  night_workers,
        },
    }


# ─────────────────────────────────────────────────────────
# PUBLIC: schedule_day — single-day compat shim
# ─────────────────────────────────────────────────────────
def schedule_day(
    day_str:       str,
    day_movers:    int  = 2,
    night_workers: int  = 2,
    supervisor:    bool = True,
    move2_window:  int  = 60,
) -> dict:
    """Single-day wrapper around schedule_range. Used by app.py."""
    result = schedule_range(day_str, day_str, day_movers, night_workers, supervisor, move2_window)
    day    = result["days"][0] if result["days"] else {"tasks":[], "warnings":[], "summary":{}}
    return {
        "date":     day_str,
        "tasks":    day["tasks"],
        "warnings": day["warnings"],
        "summary":  day["summary"],
        "source":   result["source"],
    }
