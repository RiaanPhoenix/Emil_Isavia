"""
Central configuration for the Emil Isavia valet-parking system.
Override any value via environment variables (prefixed ISAVIA_).
"""

import os

# ── External Flight API ─────────────────────────────────────────────
# We use the free OpenSky Network REST API by default.
# Set ISAVIA_FLIGHT_API_KEY for AviationStack / AirLabs etc.
FLIGHT_API_PROVIDER = os.getenv("ISAVIA_FLIGHT_API_PROVIDER", "opensky")
FLIGHT_API_KEY = os.getenv("ISAVIA_FLIGHT_API_KEY", "")
AIRPORT_ICAO = os.getenv("ISAVIA_AIRPORT_ICAO", "BIKF")  # Keflavík

# ── Physical layout ─────────────────────────────────────────────────
CAPACITY_RECEPTION  = int(os.getenv("ISAVIA_CAP_RECEPTION", 14))
CAPACITY_GULL       = int(os.getenv("ISAVIA_CAP_GULL", 50))
CAPACITY_P3         = int(os.getenv("ISAVIA_CAP_P3", 150))
CAPACITY_DELIVERY   = int(os.getenv("ISAVIA_CAP_DELIVERY", 20))

# ── Travel times between zones (minutes, one-way by car) ───────────
TRAVEL_RECEPTION_TO_GULL     = float(os.getenv("ISAVIA_TT_REC_GULL", 3))
TRAVEL_RECEPTION_TO_P3       = float(os.getenv("ISAVIA_TT_REC_P3", 8))
TRAVEL_GULL_TO_DELIVERY      = float(os.getenv("ISAVIA_TT_GULL_DEL", 4))
TRAVEL_P3_TO_DELIVERY        = float(os.getenv("ISAVIA_TT_P3_DEL", 9))
TRAVEL_DELIVERY_TO_RECEPTION = float(os.getenv("ISAVIA_TT_DEL_REC", 3))
# Walk-back time (staff walks back after driving a car)
WALK_GULL_TO_RECEPTION       = float(os.getenv("ISAVIA_WK_GULL_REC", 5))
WALK_P3_TO_RECEPTION         = float(os.getenv("ISAVIA_WK_P3_REC", 12))
WALK_DELIVERY_TO_GULL        = float(os.getenv("ISAVIA_WK_DEL_GULL", 6))
WALK_DELIVERY_TO_P3          = float(os.getenv("ISAVIA_WK_DEL_P3", 13))

# ── Operational parameters ──────────────────────────────────────────
# How early (minutes before flight arrival) a car must be at delivery
DELIVERY_LEAD_TIME  = float(os.getenv("ISAVIA_DELIVERY_LEAD", 15))
# Time slot granularity for the optimisation model (minutes)
TIME_SLOT_MINUTES   = int(os.getenv("ISAVIA_SLOT_MIN", 15))
# Planning horizon (hours)
PLANNING_HORIZON_H  = int(os.getenv("ISAVIA_HORIZON_H", 24))
# Maximum staff available
MAX_STAFF           = int(os.getenv("ISAVIA_MAX_STAFF", 10))

# ── Simulation parameters ──────────────────────────────────────────
SIM_RUNS            = int(os.getenv("ISAVIA_SIM_RUNS", 10))
SIM_RANDOM_SEED     = int(os.getenv("ISAVIA_SIM_SEED", 42))
# Stochastic noise: std-dev of flight delay (minutes, normal distribution)
SIM_FLIGHT_DELAY_STD = float(os.getenv("ISAVIA_SIM_DELAY_STD", 15))
# Stochastic noise: std-dev of driving time multiplier
SIM_DRIVE_TIME_STD   = float(os.getenv("ISAVIA_SIM_DRIVE_STD", 0.15))

# ── Flask / web ─────────────────────────────────────────────────────
SECRET_KEY = os.getenv("ISAVIA_SECRET_KEY", "dev-change-me")
DEBUG      = os.getenv("ISAVIA_DEBUG", "true").lower() == "true"
PORT       = int(os.getenv("ISAVIA_PORT", 5000))
