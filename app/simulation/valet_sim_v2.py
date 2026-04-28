"""
isavia_valet_sim_v2.py
======================
Scenario tester for Isavia Premium Valet Parking.

Employees set parameters (staff levels, retrieval lead time, stochastic noise,
demand scale) and run the simulation to see how the system performs under those
conditions. Results can be compared across scenarios on the website.

The optimization model (separate) finds the best solution.
This model answers: "how does our system behave if we do X?"
"""

import simpy
import random
import requests
import base64
import calendar
import numpy as np
from dataclasses import dataclass
from datetime import datetime, timezone, date, timedelta
from typing import Optional, List, Dict

# =============================================================================
# API
# =============================================================================

API_URL      = "https://parking-api-dev-d8b2ejb0asc0gbec.northeurope-01.azurewebsites.net"
API_USER     = "parking"
API_PASSWORD = "***REDACTED***"

# =============================================================================
# PHYSICAL CONSTANTS
# =============================================================================

CAP_RECEPTION = 14
CAP_GULL      = 50
CAP_P3        = 150
CAP_RETURN    = 20
KEYBOX_TIME   = 1.5  # minutes to handle keybox

BASE_TRAVEL = {
    ("reception", "gull"):   5,
    ("reception", "p3"):    10,
    ("gull",      "return"): 6,
    ("p3",        "return"): 8,
}

BASE_WALKBACK = {
    ("gull",   "reception"): 3,
    ("p3",     "reception"): 5,
    ("return", "gull"):      3,
    ("return", "p3"):        4,
}

# =============================================================================
# SCENARIO PARAMETERS
# =============================================================================

@dataclass
class SimParams:
    date_start:             str   = "2025-01-01"
    date_end:               str   = "2025-01-07"
    n_runs:                 int   = 10
    staff_day:              int   = 3   # staff 05:30–17:30 (one always on phone)
    staff_night:            int   = 2   # staff 17:30–05:30 (one always on phone)
    has_supervisor:         bool  = True  # supervisor 08:00–20:00 adds one extra mover
    retrieval_lead:         int   = 90
    stochastic:             bool  = False
    flight_delay_std:       float = 15.0
    drive_time_variability: float = 0.15
    demand_scale:           float = 1.0

# =============================================================================
# ENTITY
# =============================================================================

@dataclass
class Car:
    car_id:            str
    arrival_min:       float
    depart_min:        float
    actual_return_min: float
    zone:              str   = ""
    ready_min:         float = -1
    late:              bool  = False

# =============================================================================
# DATA
# =============================================================================

def _parse(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


def _month_chunks(ds: str, de: str):
    current = date.fromisoformat(ds)
    end     = date.fromisoformat(de)
    while current <= end:
        last_day  = calendar.monthrange(current.year, current.month)[1]
        chunk_end = min(date(current.year, current.month, last_day), end)
        yield current.isoformat(), chunk_end.isoformat()
        current = chunk_end + timedelta(days=1)


def fetch_bookings(params: SimParams) -> List[Dict]:
    token   = base64.b64encode(f"{API_USER}:{API_PASSWORD}".encode()).decode()
    headers = {"Authorization": f"Basic {token}"}
    raw     = []
    for cs, ce in _month_chunks(params.date_start, params.date_end):
        resp = requests.get(
            f"{API_URL}/premium-bookings",
            params={"date_start": cs, "date_end": ce},
            headers=headers, timeout=30,
        )
        resp.raise_for_status()
        raw.extend(resp.json().get("bookings", []))
    raw.sort(key=lambda b: b.get("arrival_datetime") or "")
    return raw


def build_cars(
    bookings:  List[Dict],
    sim_start: datetime,
    params:    SimParams,
    rng:       random.Random,
    np_rng:    np.random.Generator,
) -> List[Car]:
    base = []
    for b in bookings:
        a = _parse(b.get("arrival_datetime"))
        d = _parse(b.get("departure_datetime"))
        if not a or not d:
            continue
        a_min = (a - sim_start).total_seconds() / 60
        d_min = (d - sim_start).total_seconds() / 60
        if d_min > a_min:
            base.append((str(b.get("car_id")), a_min, d_min))

    if params.demand_scale < 1.0:
        base = rng.sample(base, max(1, int(len(base) * params.demand_scale)))
    elif params.demand_scale > 1.0:
        extra = int(len(base) * (params.demand_scale - 1.0))
        for _ in range(extra):
            src    = rng.choice(base)
            jitter = rng.uniform(-30, 30)
            base.append((src[0] + "_dup", src[1] + jitter, src[2] + jitter))

    cars = []
    for car_id, a_min, d_min in base:
        delay = float(np_rng.normal(0, params.flight_delay_std)) if params.stochastic else 0.0
        cars.append(Car(car_id, a_min, d_min, actual_return_min=d_min + delay))

    cars.sort(key=lambda c: c.arrival_min)
    return cars

# =============================================================================
# STAFFING
# =============================================================================

def movers_now(sim_minute: float, sim_start: datetime, params: SimParams) -> int:
    tod      = (sim_start.hour * 60 + sim_start.minute + int(sim_minute)) % 1440
    on_shift = params.staff_day if 5*60+30 <= tod < 17*60+30 else params.staff_night
    if params.has_supervisor and 8*60 <= tod < 20*60:
        on_shift += 1
    return max(0, on_shift - 1)  # -1 for phone duty; can be 0 if only 1 on shift

# =============================================================================
# SIMULATION
# =============================================================================

class ParkingSim:
    def __init__(self, cars: List[Car], sim_start: datetime,
                 params: SimParams, seed: int = 0):
        self.cars      = cars
        self.sim_start = sim_start
        self.params    = params
        self.rng       = random.Random(seed)
        self.np_rng    = np.random.default_rng(seed)

        self.env       = simpy.Environment()
        self.reception = simpy.Container(self.env, CAP_RECEPTION, init=0)
        self.gull      = simpy.Container(self.env, CAP_GULL,      init=0)
        self.p3        = simpy.Container(self.env, CAP_P3,        init=0)
        self.ret       = simpy.Container(self.env, CAP_RETURN,    init=0)

        # Movers as a token pool. get(1) blocks when 0 tokens = 0 movers available.
        # Using Container (not Resource) so capacity=0 is valid.
        init_movers         = movers_now(0, sim_start, params)
        self._mover_target  = init_movers
        self.movers         = simpy.Container(self.env, capacity=99, init=init_movers)

        self.work_car = simpy.Resource(self.env, capacity=1)
        self.peak     = {"reception": 0, "gull": 0, "p3": 0, "return": 0}

    def run(self) -> Dict:
        for car in self.cars:
            self.env.process(self.car_process(car))
        self.env.process(self.shift_updater())
        end = max(c.actual_return_min for c in self.cars) + 120
        self.env.run(until=end)
        return self._kpis()

    # -- Car lifecycle --------------------------------------------------------

    def car_process(self, car: Car):
        env = self.env

        # 1. Customer drops off car
        yield env.timeout(max(0, car.arrival_min))
        yield self.reception.put(1)
        self._track("reception", self.reception)
        yield self.movers.get(1)
        yield env.timeout(KEYBOX_TIME)
        self._free_mover()

        # 2. Move car: Reception → Storage (Gull or P3)
        zone    = self._pick_zone()
        storage = self.gull if zone == "gull" else self.p3
        car.zone = zone

        yield self.reception.get(1)
        self._track("reception", self.reception)
        yield self.movers.get(1)
        yield env.timeout(self._drive("reception", zone))
        self._free_mover()
        yield storage.put(1)
        self._track(zone, storage)
        env.process(self._return_work_car(zone, "reception"))

        # 3. Wait until retrieval time
        retrieve_at = (car.depart_min
                       - self.params.retrieval_lead
                       - self._drive(zone, "return")
                       - KEYBOX_TIME)
        yield env.timeout(max(0, retrieve_at - env.now))

        # 4. Move car: Storage → Return
        yield storage.get(1)
        self._track(zone, storage)
        yield self.movers.get(1)
        yield env.timeout(self._drive(zone, "return"))
        self._free_mover()
        yield self.ret.put(1)
        self._track("return", self.ret)
        car.ready_min = env.now

        yield self.movers.get(1)
        yield env.timeout(KEYBOX_TIME)
        self._free_mover()
        env.process(self._return_work_car("return", zone))

        # Was the car ready before the customer arrived?
        car.late = car.ready_min > car.actual_return_min

        # 5. Customer picks up car
        yield env.timeout(max(0, car.actual_return_min - env.now))
        yield self.ret.get(1)
        self._track("return", self.ret)

    # -- Helpers --------------------------------------------------------------

    def _free_mover(self):
        """Return mover token only up to the current shift's limit.
        Tokens from ended shifts are absorbed here rather than returned."""
        if int(self.movers.level) < self._mover_target:
            self.movers.put(1)

    def _drive(self, frm: str, to: str) -> float:
        base = BASE_TRAVEL.get((frm, to), 5.0)
        if self.params.stochastic:
            base = max(0.5, base + float(
                self.np_rng.normal(0, self.params.drive_time_variability * base)))
        return base

    def _return_work_car(self, frm: str, to: str):
        """Staff drives shared work car back. Needs a free mover AND the work car."""
        base = BASE_WALKBACK.get((frm, to), 3.0)
        if self.params.stochastic:
            base = max(0.5, base + float(
                self.np_rng.normal(0, self.params.drive_time_variability * base)))
        yield self.movers.get(1)
        with self.work_car.request() as cr:
            yield cr
            yield self.env.timeout(base)
        self._free_mover()

    def shift_updater(self):
        """Add mover tokens when a bigger shift starts; absorbed by _free_mover when shift shrinks."""
        while True:
            yield self.env.timeout(1)
            new_target = movers_now(self.env.now, self.sim_start, self.params)
            if new_target > self._mover_target:
                self.movers.put(new_target - self._mover_target)
            self._mover_target = new_target

    def _pick_zone(self) -> str:
        gf = CAP_GULL - int(self.gull.level)
        pf = CAP_P3   - int(self.p3.level)
        if gf <= 0: return "p3"
        if pf <= 0: return "gull"
        return random.choices(["gull", "p3"], weights=[gf, pf])[0]

    def _track(self, name: str, container: simpy.Container):
        level = int(container.level)
        if level > self.peak[name]:
            self.peak[name] = level

    def _kpis(self) -> Dict:
        # Cars never retrieved (stuck waiting for movers) count as late
        retrieved  = [c for c in self.cars if c.ready_min >= 0]
        on_time    = [c for c in retrieved if not c.late]
        total      = len(self.cars)
        late_count = total - len(on_time)
        earliness  = [c.actual_return_min - c.ready_min for c in on_time]
        return {
            "total_cars":     total,
            "late_count":     late_count,
            "service_level":  round(len(on_time) / total, 4) if total else 0,
            "avg_earliness":  round(float(np.mean(earliness)), 1) if earliness else 0,
            "min_earliness":  round(float(np.min(earliness)),  1) if earliness else 0,
            "reception_peak": self.peak["reception"],
            "gull_peak":      self.peak["gull"],
            "p3_peak":        self.peak["p3"],
            "return_peak":    self.peak["return"],
        }

# =============================================================================
# SCENARIO RUNNER
# =============================================================================

def run_scenario(params: SimParams) -> Dict:
    bookings = fetch_bookings(params)
    if not bookings:
        return {"error": "No bookings returned from API", "params": _params_dict(params)}

    first_dt  = min(_parse(b["arrival_datetime"]) for b in bookings
                    if b.get("arrival_datetime"))
    sim_start = first_dt.replace(hour=0, minute=0, second=0, microsecond=0)

    replications = []
    for i in range(params.n_runs):
        seed  = 1000 + i
        cars  = build_cars(bookings, sim_start, params,
                           random.Random(seed), np.random.default_rng(seed))
        result        = ParkingSim(cars, sim_start, params, seed=seed).run()
        result["run"] = i + 1
        replications.append(result)

    return {
        "params":         _params_dict(params),
        "bookings_count": len(bookings),
        "sim_start":      sim_start.isoformat(),
        "summary":        _summarise(replications),
        "replications":   replications,
    }


def _summarise(reps: List[Dict]) -> Dict:
    kpis = ["late_count", "service_level", "avg_earliness", "min_earliness",
            "reception_peak", "gull_peak", "p3_peak", "return_peak"]
    caps = {"reception_peak": CAP_RECEPTION, "gull_peak": CAP_GULL,
            "p3_peak": CAP_P3, "return_peak": CAP_RETURN}
    out  = {}
    for k in kpis:
        vals  = [r[k] for r in reps]
        entry = {"mean": round(float(np.mean(vals)), 3),
                 "std":  round(float(np.std(vals)),  3)}
        if k in caps:
            entry["capacity"]    = caps[k]
            entry["utilisation"] = round(entry["mean"] / caps[k], 3)
        out[k] = entry
    return out


def _params_dict(p: SimParams) -> Dict:
    return {
        "date_start":             p.date_start,
        "date_end":               p.date_end,
        "n_runs":                 p.n_runs,
        "staff_day":              p.staff_day,
        "staff_night":            p.staff_night,
        "has_supervisor":         p.has_supervisor,
        "retrieval_lead":         p.retrieval_lead,
        "stochastic":             p.stochastic,
        "flight_delay_std":       p.flight_delay_std,
        "drive_time_variability": p.drive_time_variability,
        "demand_scale":           p.demand_scale,
    }
