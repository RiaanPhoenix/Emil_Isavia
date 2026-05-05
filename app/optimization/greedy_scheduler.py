# greedy_scheduler.py
# ---------------------------------------------------------
# FIFO Greedy Scheduler með backhaul
# Kallar á þetta úr valet.py eða vefsíðunni
#
# Notkun:
#   from greedy_scheduler import fifo_schedule, ParkingTracker
# ---------------------------------------------------------

from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional

# ─────────────────────────────────────────────────────────
# STILLINGAR
# ─────────────────────────────────────────────────────────
NUM_WORKERS       = 2
PROCESS_MIN       = 1.5
RETURN_BUFFER_MIN = 90
DROPOFF_BEFORE_H  = 3
BACKHAUL_WINDOW_H = 4  # ef return_ddl er innan 4 klst → nýta ferðina

CAP_MOTT = 14
CAP_GULL = 50
CAP_P3   = 150
CAP_SKIL = 20

LOC_OFFICE = "Office"
LOC_MOTT   = "Móttökustæði"
LOC_GULL   = "Gull"
LOC_P3     = "P3"
LOC_SKIL   = "Skilastæði"




# ─────────────────────────────────────────────────────────
# BÍLAHLUTUR
# ─────────────────────────────────────────────────────────
class Car:
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
# HJÁLPARFÖLL
# ─────────────────────────────────────────────────────────
def fmt(t: datetime) -> str:
    return t.strftime("%Y-%m-%d %H:%M")

def to_mins(midnight: datetime, t: datetime) -> float:
    return (t - midnight).total_seconds() / 60.0


# ─────────────────────────────────────────────────────────
# STÆÐARAKNINGARHLUTUR
# ─────────────────────────────────────────────────────────
class ParkingTracker:
    """Rekur hversu margir bílar eru í hverju svæði á hverjum tíma."""

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
# BACKHAUL ATHUGUN
# ─────────────────────────────────────────────────────────
def find_backhaul(car_id_done: str,
                  loc_storage: str,
                  worker_arrives: float,
                  cars_in_storage: Dict,
                  parking: ParkingTracker,
                  d2g: Dict, d2p: Dict) -> Optional[str]:
    """
    Þegar worker kemur með bíl í geymslu — athugar hvort
    einhver bíll þar sé tilbúinn í Move2 innan 4 klst.

    Skilar car_id eða None.
    """
    window_mins = BACKHAUL_WINDOW_H * 60
    best_cid  = None
    best_rddl = float("inf")

    for cid, info in cars_in_storage.items():
        if cid == car_id_done:         continue
        if info["storage"] != loc_storage: continue
        if info.get("move2_scheduled"):    continue
        if info["storage_inn"] > worker_arrives: continue

        rddl           = info["rddl"]
        time_until_ddl = rddl - worker_arrives

        if 0 <= time_until_ddl <= window_mins:
            if rddl < best_rddl:
                best_rddl = rddl
                best_cid  = cid

    return best_cid


# ─────────────────────────────────────────────────────────
# AÐAL SCHEDULER
# ─────────────────────────────────────────────────────────
def fifo_schedule(cars: list,
                  d1g: Dict, d1p: Dict,
                  d2g: Dict, d2p: Dict,
                  midnight: datetime) -> Tuple[list, list]:
    """
    FIFO Greedy Scheduler með:
      1. FIFO röðun eftir dropoff tíma
      2. Stæðakapasítet — Gull fullt → P3
      3. Move2 nær return_ddl (ekki strax)
      4. Backhaul — nýtir Move1 ferð til að skila öðrum bíl

    Args:
        cars:     listi af Car hlutum
        d1g/d1p:  Move1 durations (Gull/P3) per car_id
        d2g/d2p:  Move2 durations (Gull/P3) per car_id
        midnight: datetime við miðnætti dagsins

    Returns:
        (rows, warnings)
        rows:     listi af task dict-um (einn per Move)
        warnings: listi af viðvörunarstrengum
    """
    sorted_cars     = sorted(cars, key=lambda c: c.dropoff)
    worker_free     = [0.0] * NUM_WORKERS
    parking         = ParkingTracker()
    cars_in_storage: Dict = {}
    rows            = []
    warnings        = []

    for c in sorted_cars:
        cid  = c.car_id
        rel  = max(0.0,   to_mins(midnight, c.dropoff))
        sddl = min(1439.0, to_mins(midnight, c.storage_ddl))
        rddl = min(1439.0, to_mins(midnight, c.return_ddl))

        dur1_g, dur2_g = d1g[cid], d2g[cid]
        dur1_p, dur2_p = d1p[cid], d2p[cid]

        # ── Velja geymslu ─────────────────────────────────
        wk1_test = min(range(NUM_WORKERS), key=lambda k: max(worker_free[k], rel))
        s1m_test = max(worker_free[wk1_test], rel)

        gull_laus = not parking.is_full(LOC_GULL, s1m_test + dur1_g / 2)
        p3_laus   = not parking.is_full(LOC_P3,   s1m_test + dur1_p / 2)

        if gull_laus:
            storage, dur1, dur2 = "Gull", dur1_g, dur2_g
            loc_storage = LOC_GULL
        elif p3_laus:
            storage, dur1, dur2 = "P3", dur1_p, dur2_p
            loc_storage = LOC_P3
            warnings.append(f"  ⚠ {cid}: Gull fullt → P3")
        else:
            storage, dur1, dur2 = "Gull", dur1_g, dur2_g
            loc_storage = LOC_GULL
            warnings.append(f"  ⚠ {cid}: Gull og P3 full — bíður")

        lbl1 = f"{LOC_MOTT} → {loc_storage}"
        lbl2 = f"{loc_storage} → {LOC_SKIL}"

        # ── MOVE1 ─────────────────────────────────────────
        wk1 = min(range(NUM_WORKERS), key=lambda k: max(worker_free[k], rel))
        s1m = max(worker_free[wk1], rel)
        e1m = min(s1m + dur1, sddl)
        s1m = e1m - dur1
        worker_free[wk1] = e1m

        parking.add(LOC_MOTT, rel, s1m)
        storage_inn = e1m

        cars_in_storage[cid] = {
            "storage":        loc_storage,
            "storage_inn":    storage_inn,
            "rddl":           rddl,
            "dur2":           dur2,
            "car":            c,
            "move2_scheduled": False,
        }

        # ── BACKHAUL ──────────────────────────────────────
        bh_cid = find_backhaul(
            car_id_done    = cid,
            loc_storage    = loc_storage,
            worker_arrives = e1m,
            cars_in_storage= cars_in_storage,
            parking        = parking,
            d2g            = d2g,
            d2p            = d2p,
        )

        if bh_cid:
            bh      = cars_in_storage[bh_cid]
            bh_car  = bh["car"]
            bh_dur2 = bh["dur2"]
            bh_rddl = bh["rddl"]
            bh_stor = bh["storage"]
            bh_lbl2 = f"{bh_stor} → {LOC_SKIL}"

            bh_s2m = e1m
            bh_e2m = bh_s2m + bh_dur2
            if bh_e2m > bh_rddl:
                bh_s2m = max(storage_inn, bh_rddl - bh_dur2)
                bh_e2m = bh_s2m + bh_dur2

            worker_free[wk1] = bh_e2m
            bh_t2s = midnight + timedelta(minutes=bh_s2m)

            rows.append({
                "type":           "MOVE2",
                "carId":          bh_cid,
                "storage":        bh_stor,
                "worker":         f"W{wk1 + 1}",
                "start":          fmt(bh_t2s),
                "end":            fmt(bh_t2s + timedelta(minutes=bh_dur2)),
                "durationMin":    round(bh_dur2, 1),
                "move":           bh_lbl2,
                "depFlight":      fmt(bh_car.dep_flight),
                "arrFlight":      fmt(bh_car.arr_flight),
                "storageDeadline":fmt(bh_car.storage_ddl),
                "returnDeadline": fmt(bh_car.return_ddl),
                "note":           f"BACKHAUL eftir Move1 á {cid}",
            })

            parking.add(bh_stor, bh["storage_inn"], bh_s2m)
            parking.add(LOC_SKIL, bh_e2m, bh_e2m + 60)
            cars_in_storage[bh_cid]["move2_scheduled"] = True
            warnings.append(
                f"  ✓ BACKHAUL: W{wk1+1} skilar {bh_cid} "
                f"á leiðinni eftir Move1 á {cid}"
            )

        # ── MOVE2 — nær return_ddl ────────────────────────
        ideal_s2m  = rddl - dur2
        earliest_m2 = e1m
        s2m = max(earliest_m2, ideal_s2m)
        e2m = s2m + dur2

        attempts = 0
        while parking.is_full(LOC_SKIL, s2m + dur2/2) and s2m > earliest_m2:
            s2m = max(earliest_m2, s2m - 10)
            e2m = s2m + dur2
            attempts += 1
            if attempts > 100: break

        if parking.is_full(LOC_SKIL, s2m + dur2/2):
            warnings.append(f"  ⚠ {cid}: Skilastæði fullt")

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
            "type":           "MOVE1",
            "carId":          cid,
            "storage":        storage,
            "worker":         f"W{wk1 + 1}",
            "start":          fmt(t1s),
            "end":            fmt(t1s + timedelta(minutes=dur1)),
            "durationMin":    round(dur1, 1),
            "move":           lbl1,
            "depFlight":      fmt(c.dep_flight),
            "arrFlight":      fmt(c.arr_flight),
            "storageDeadline":fmt(c.storage_ddl),
            "returnDeadline": fmt(c.return_ddl),
            "note":           "",
        })
        rows.append({
            "type":           "MOVE2",
            "carId":          cid,
            "storage":        storage,
            "worker":         f"W{wk2 + 1}",
            "start":          fmt(t2s),
            "end":            fmt(t2s + timedelta(minutes=dur2)),
            "durationMin":    round(dur2, 1),
            "move":           lbl2,
            "depFlight":      fmt(c.dep_flight),
            "arrFlight":      fmt(c.arr_flight),
            "storageDeadline":fmt(c.storage_ddl),
            "returnDeadline": fmt(c.return_ddl),
            "note":           "",
        })

    return rows, warnings


# ─────────────────────────────────────────────────────────
# schedule_day — public entry point used by app.py
# ─────────────────────────────────────────────────────────
import base64 as _base64
import json as _json
import os as _os
import urllib.request as _urllib_req

try:
    from dotenv import load_dotenv as _load_dotenv
    _load_dotenv()
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

_SD_API_URL      = _os.getenv("PARKING_API_URL",     "https://parking-api-dev-d8b2ejb0asc0gbec.northeurope-01.azurewebsites.net")
_SD_API_USER     = _os.getenv("PARKING_API_USERNAME", _os.getenv("API_USER", ""))
_SD_API_PASSWORD = _os.getenv("PARKING_API_PASSWORD", _os.getenv("API_PASSWORD", ""))

_DEFAULT_DAY_MOVERS    = 2
_DEFAULT_NIGHT_WORKERS = 2
_DEFAULT_SUPERVISOR    = True
_DEFAULT_MOVE2_WINDOW  = 60


def _sd_auth():
    return "Basic " + _base64.b64encode(f"{_SD_API_USER}:{_SD_API_PASSWORD}".encode()).decode()


def _sd_api_get(endpoint):
    url = _SD_API_URL.rstrip("/") + "/" + endpoint.lstrip("/")
    req = _urllib_req.Request(url, headers={"Authorization": _sd_auth(), "Accept": "application/json"})
    with _urllib_req.urlopen(req, timeout=30) as r:
        return _json.loads(r.read().decode("utf-8"))


def _sd_parse_dt(s: str) -> datetime:
    s = str(s).strip().replace("T", " ").split(".")[0].split("+")[0].replace("Z", "").strip()
    for f in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d",
              "%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%Y",
              "%d/%m/%Y %H:%M", "%m/%d/%Y %H:%M"):
        try:
            return datetime.strptime(s, f)
        except ValueError:
            pass
    raise ValueError(f"Cannot parse: {s!r}")


def _sd_load_cars(day_str: str):
    ID  = ["carId","car_id","CarId","id","bookingId","licensePlate","plateNumber"]
    DEP = ["departure","departureFlight","dep","departureTime","departureDate","Departure"]
    ARR = ["arrival","arrivalFlight","arr","arrivalTime","arrivalDate","Arrival","returnDate"]

    day_dt   = datetime.strptime(day_str, "%Y-%m-%d")
    lookback = (day_dt - timedelta(days=30)).strftime("%Y-%m-%d")
    day0     = day_dt.replace(hour=0,  minute=0,  second=0, microsecond=0)
    day1     = day_dt.replace(hour=23, minute=59, second=0, microsecond=0)

    def pick(rec, keys):
        for k in keys:
            if k in rec and rec[k] not in (None, ""): return str(rec[k])
        nl = lambda s: s.lower().replace("_","").replace(" ","")
        for k in keys:
            for rk in rec:
                if nl(k) in nl(rk) and rec[rk] not in (None,""): return str(rec[rk])
        return None

    try:
        ep     = f"/premium-bookings?date_start={lookback}&date_end={day_str}"
        result = _sd_api_get(ep)
        raw    = result if isinstance(result, list) else (
            result.get("data") or result.get("bookings") or result.get("reservations") or [])
    except Exception as e:
        return [], f"api_error: {e}", 0

    cars, skipped = [], 0
    for rec in raw:
        cid     = pick(rec, ID)
        dep_raw = pick(rec, DEP)
        arr_raw = pick(rec, ARR)
        if not cid or not dep_raw or not arr_raw:
            skipped += 1; continue
        try:
            dep = _sd_parse_dt(dep_raw)
            arr = _sd_parse_dt(arr_raw)
        except ValueError:
            skipped += 1; continue
        if dep > arr: dep, arr = arr, dep
        c = Car(cid, dep, arr)
        if (day0 <= c.dropoff <= day1) or (day0 <= c.return_ddl <= day1):
            cars.append(c)

    return cars, "api", skipped


def schedule_day(
    day_str: str,
    day_movers: int = _DEFAULT_DAY_MOVERS,
    night_workers: int = _DEFAULT_NIGHT_WORKERS,
    supervisor: bool = _DEFAULT_SUPERVISOR,
    move2_window: int = _DEFAULT_MOVE2_WINDOW,
) -> dict:
    """Public entry point for app.py — loads bookings and runs fifo_schedule."""
    midnight = datetime.strptime(day_str, "%Y-%m-%d")
    cars, source, skipped = _sd_load_cars(day_str)

    if not cars:
        return {
            "date":     day_str,
            "tasks":    [],
            "warnings": [f"No bookings found for {day_str} (source: {source})"],
            "summary":  {"total_cars": 0, "total_work_min": 0, "n_gull": 0, "n_p3": 0, "skipped": skipped},
            "storage":  None,
            "source":   source,
        }

    dur1_gull = _WALK_GULL + PROCESS_MIN + _DRIVE_MOTT_GULL
    dur1_p3   = _WALK_P3   + PROCESS_MIN + _DRIVE_MOTT_P3
    dur2_gull = _DRIVE_GULL_SKIL + _WALK_SKIL
    dur2_p3   = _DRIVE_P3_SKIL   + _WALK_SKIL

    d1g = {c.car_id: dur1_gull for c in cars}
    d1p = {c.car_id: dur1_p3   for c in cars}
    d2g = {c.car_id: dur2_gull for c in cars}
    d2p = {c.car_id: dur2_p3   for c in cars}

    tasks, warnings = fifo_schedule(cars, d1g, d1p, d2g, d2p, midnight)

    n_gull     = sum(1 for r in tasks if r["type"] == "MOVE1" and r["storage"] == "Gull")
    n_p3       = sum(1 for r in tasks if r["type"] == "MOVE1" and r["storage"] == "P3")
    total_work = sum(r["durationMin"] for r in tasks)

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
            "day_movers":     day_movers,
            "night_workers":  night_workers,
            "supervisor":     supervisor,
            "move2_window":   move2_window,
        },
        "storage": "Gull" if n_gull >= n_p3 else "P3",
        "source":  source,
    }
