# valet_optimizer.py
# ---------------------------------------------------------
# Aðalforrit — sækir gögn, keyrir scheduler, vistar niðurstöður
#
# Keyrsla:
# python3 valet_optimizer.py → DAY_DEFAULT
# python3 valet_optimizer.py 2026-04-27 → tiltekinn dagur
# python3 valet_optimizer.py 2026-04-27 csv
# ---------------------------------------------------------

import csv, sys, json, base64, os
import urllib.request
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional

from greedy_scheduler import fifo_schedule, fmt, to_mins

# ─────────────────────────────────────────────────────────
# STILLINGAR — lesnar úr .env eða environment variables
# ─────────────────────────────────────────────────────────
import os
try:
    from dotenv import load_dotenv
    load_dotenv()  # les .env skrána ef hún er til
except ImportError:
    pass  # dotenv ekki uppsett — notar bara os.environ

API_URL      = os.environ.get("API_URL",      "https://parking-api-dev-d8b2ejb0asc0gbec.northeurope-01.azurewebsites.net")
API_USER     = os.environ.get("API_USER",     "")
API_PASSWORD = os.environ.get("API_PASSWORD", "")

FINAL_CSV = os.environ.get("FINAL_CSV", "final_output.csv")
TM_CSV    = os.environ.get("TM_CSV",    "timematrix.csv")

PROCESS_MIN       = 1.5
DROPOFF_BEFORE_H  = 3
RETURN_BUFFER_MIN = 90

LOC_OFFICE = "Office"
LOC_MOTT   = "Móttökustæði"
LOC_GULL   = "Gull"
LOC_P3     = "P3"
LOC_SKIL   = "Skilastæði"

DAY_DEFAULT = "2026-04-27"


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
def parse_dt(s: str) -> datetime:
    s = str(s).strip().replace("T", " ").split(".")[0].split("+")[0].replace("Z","").strip()
    for f in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d",
              "%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%Y",
              "%d/%m/%Y %H:%M", "%m/%d/%Y %H:%M"):
        try: return datetime.strptime(s, f)
        except ValueError: pass
    raise ValueError(f"Get ekki þáttað: {s!r}")


# ─────────────────────────────────────────────────────────
# TIMEMATRIX
# ─────────────────────────────────────────────────────────
def load_timematrix() -> Tuple[Dict, Dict]:
    def detect_delim(path):
        with open(path, encoding="utf-8-sig", errors="ignore") as f:
            return ";" if f.readline().count(";") >= 2 else ","

    def to_float(cell):
        c = cell.strip().lower()
        if not c or c in ("n/a","na","#n/a"): return None
        try: return float(cell.strip().replace(",","."))
        except: return None

    with open(TM_CSV, newline="", encoding="utf-8-sig", errors="ignore") as f:
        grid = [[c or "" for c in row]
                for row in csv.reader(f, delimiter=detect_delim(TM_CSV))]

    def parse_table(label):
        ll = label.lower()
        sr = sc = -1
        for r, row in enumerate(grid):
            for c, cell in enumerate(row):
                if cell.strip().lower() == ll:
                    sr, sc = r, c; break
            if sr != -1: break
        if sr == -1: raise ValueError(f"'{label}' fannst ekki")
        header    = grid[sr]
        dest_cols = [(c, header[c].strip())
                     for c in range(sc+1, len(header)) if header[c].strip()]
        out = {}
        for r in range(sr+1, len(grid)):
            row = grid[r]
            if sc >= len(row): continue
            rn = row[sc].strip()
            if not rn or rn.lower() in ("gangandi","keyrandi"): break
            for ci, dest in dest_cols:
                if ci < len(row):
                    v = to_float(row[ci])
                    if v is not None: out[(rn, dest)] = v
        return out

    return parse_table("Gangandi"), parse_table("Keyrandi")

def travel(d, a, b):
    if (a,b) in d: return d[(a,b)]
    if (b,a) in d: return d[(b,a)]
    raise KeyError(f"Vantar tíma '{a}' <-> '{b}'")

def mission_dur(walk, drive, frm, to):
    return (travel(walk, LOC_OFFICE, frm)
            + PROCESS_MIN
            + travel(drive, frm, to)
            + travel(walk, to, LOC_OFFICE))


# ─────────────────────────────────────────────────────────
# API
# ─────────────────────────────────────────────────────────
def _auth():
    return "Basic " + base64.b64encode(f"{API_USER}:{API_PASSWORD}".encode()).decode()

def api_get(endpoint):
    url = API_URL.rstrip("/") + "/" + endpoint.lstrip("/")
    req = urllib.request.Request(url, headers={"Authorization": _auth(), "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))

def api_post(endpoint, payload):
    url  = API_URL.rstrip("/") + "/" + endpoint.lstrip("/")
    data = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
    req  = urllib.request.Request(url, data=data, method="POST", headers={
        "Authorization": _auth(), "Content-Type": "application/json", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read().decode("utf-8")
        return json.loads(raw) if raw.strip() else {}


# ─────────────────────────────────────────────────────────
# HLAÐA BÍLUM
# ─────────────────────────────────────────────────────────
def parse_records(records, id_keys, dep_keys, arr_keys, day_str):
    day  = datetime.strptime(day_str, "%Y-%m-%d")
    day0 = day.replace(hour=0,  minute=0,  second=0, microsecond=0)
    day1 = day.replace(hour=23, minute=59, second=0, microsecond=0)

    def pick(rec, keys):
        for k in keys:
            if k in rec and rec[k] not in (None, ""): return str(rec[k])
        nl = lambda s: s.lower().replace("_","").replace(" ","")
        for k in keys:
            for rk in rec:
                if nl(k) in nl(rk) and rec[rk] not in (None,""): return str(rec[rk])
        return None

    cars, skipped = [], 0
    for rec in records:
        cid     = pick(rec, id_keys)
        dep_raw = pick(rec, dep_keys)
        arr_raw = pick(rec, arr_keys)
        if not cid or not dep_raw or not arr_raw:
            skipped += 1; continue
        try:
            dep = parse_dt(dep_raw)
            arr = parse_dt(arr_raw)
        except ValueError:
            skipped += 1; continue
        if dep > arr: dep, arr = arr, dep
        c = Car(cid, dep, arr)
        if (day0 <= c.dropoff <= day1) or (day0 <= c.return_ddl <= day1):
            cars.append(c)

    if skipped: print(f"  ⚠ {skipped} færslur slepptar")
    return cars

def load_cars(day_str, force_csv=False):
    ID  = ["carId","car_id","CarId","id","bookingId","licensePlate","plateNumber"]
    DEP = ["departure","departureFlight","dep","departureTime","departureDate","Departure"]
    ARR = ["arrival","arrivalFlight","arr","arrivalTime","arrivalDate","Arrival","returnDate"]

    if not force_csv:
        print("  → Reyni API...")
        ep = f"/premium-bookings?date_start={day_str}&date_end={day_str}"
        try:
            result = api_get(ep)
            raw = result if isinstance(result, list) else (
                result.get("data") or result.get("bookings") or
                result.get("reservations") or [])
            print(f"  ✓ API — {len(raw)} færslur")
            if raw:
                print(f"  JSON lyklar: {list(raw[0].keys())}")
            cars = parse_records(raw, ID, DEP, ARR, day_str)
            print(f"  ✓ {len(cars)} bílar á {day_str}")
            return cars
        except Exception as e:
            print(f"  ✗ API villa: {e}")
            print(f"  ⚠ API ekki aðgengilegt — reyni CSV")

    if not os.path.exists(FINAL_CSV):
        raise FileNotFoundError(f"'{FINAL_CSV}' finnst ekki.")
    with open(FINAL_CSV, encoding="latin-1", errors="ignore") as f:
        first = f.readline()
        delim = ";" if first.count(";") >= 2 else ","
        f.seek(0)
        rows = list(csv.DictReader(f, delimiter=delim))
    cars = parse_records([dict(r) for r in rows], ID, DEP, ARR, day_str)
    print(f"  ✓ {len(cars)} bílar úr CSV")
    return cars


# ─────────────────────────────────────────────────────────
# PRENTA TÖFLU
# ─────────────────────────────────────────────────────────
def print_table(rows):
    COL = [
        ("type",          "Tegund",      6),
        ("carId",         "BíllID",      9),
        ("storage",       "Geymsla",     7),
        ("worker",        "Wrkr",        5),
        ("start",         "Byrjun",     16),
        ("end",           "Lok",        16),
        ("durationMin",   "Mín",         5),
        ("move",          "Ferð",       28),
        ("returnDeadline","Skil ddl",   16),
        ("note",          "Athugasemd", 18),
    ]
    header = " ".join(f"{lbl:<{w}}" for _, lbl, w in COL)
    sep    = "─" * len(header)
    print(f"\n{sep}\n{header}\n{sep}")
    last_car = None
    for r in rows:
        if last_car and r["carId"] != last_car and r["type"] == "MOVE1":
            print()
        print(" ".join(f"{str(r.get(k,'')):<{w}}" for k, _, w in COL))
        last_car = r["carId"]
    print(sep)


# ─────────────────────────────────────────────────────────
# AÐALFALL
# ─────────────────────────────────────────────────────────
def optimize(day_str: str, force_csv: bool = False):
    day     = datetime.strptime(day_str, "%Y-%m-%d")
    midnight = day.replace(hour=0, minute=0, second=0, microsecond=0)

    print(f"\n{'='*52}")
    print(f"  Isavia Valet Optimizer — {day_str}")
    print(f"{'='*52}")

    walk, drive = load_timematrix()
    cars        = load_cars(day_str, force_csv)

    if not cars:
        print(f"  Engir bílar á {day_str}.")
        return

    # Reikna ferðatíma
    d1g = {c.car_id: mission_dur(walk, drive, LOC_MOTT, LOC_GULL) for c in cars}
    d1p = {c.car_id: mission_dur(walk, drive, LOC_MOTT, LOC_P3)   for c in cars}
    d2g = {c.car_id: mission_dur(walk, drive, LOC_GULL, LOC_SKIL) for c in cars}
    d2p = {c.car_id: mission_dur(walk, drive, LOC_P3,   LOC_SKIL) for c in cars}

    print(f"\n  {len(cars)} bílar — keyri greedy scheduler...")

    # Kalla á greedy_scheduler
    rows, warnings = fifo_schedule(cars, d1g, d1p, d2g, d2p, midnight)

    # Viðvaranir
    if warnings:
        print(f"\n  Viðvaranir / Backhaul:")
        for w in warnings: print(w)

    # Prenta töflu
    print_table(rows)

    # Vista CSV
    out_file = f"day_plan_{day_str}.csv"
    rows.sort(key=lambda r: (r["start"], r["worker"]))
    with open(out_file, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)
    print(f"\n  ✓ Vistað: {out_file}")

    # Senda á API
    try:
        api_post("/api/schedule", {
            "date":        day_str,
            "generatedAt": datetime.now().isoformat(),
            "tasks":       rows,
        })
        print("  ✓ Sent á API")
    except Exception as e:
        print(f"  ⚠ Gat ekki sent á API: {e}")

    # Samantekt
    n_gull = sum(1 for r in rows if r["type"]=="MOVE1" and r["storage"]=="Gull")
    n_bh   = sum(1 for r in rows if "BACKHAUL" in r.get("note",""))
    total  = sum(r["durationMin"] for r in rows)

    print(f"\n{'='*52}")
    print(f"  Dagur:    {day_str}")
    print(f"  Bílar:    {len(cars)}   Gull: {n_gull}   P3: {len(cars)-n_gull}")
    print(f"  Backhaul: {n_bh} ferðir sparaðar")
    print(f"  Vinna:    {total:.0f} mín ({total/60:.1f} klst)")
    print(f"  Skrá:     {out_file}")
    print(f"{'='*52}\n")


def main():
    day       = sys.argv[1] if len(sys.argv) >= 2 else DAY_DEFAULT
    force_csv = len(sys.argv) >= 3 and sys.argv[2].lower() == "csv"
    optimize(day, force_csv)

if __name__ == "__main__":
    main()
