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
