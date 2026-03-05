"""
Emil Isavia — Premium Valet Parking Optimization & Simulation

Isavia operates a Premium valet-parking service at Keflavík International Airport.
Customers book online, drop their car at the reception area, and expect it waiting
at the delivery area when they return.

This application:
1. Pulls real flight arrival/departure data from an external API so we know
   *when* each customer departs and arrives.
2. Feeds that data into a GurobiPy optimisation model that decides:
   • Which storage zone (Gull / P3) each car goes to.
   • When each move should happen.
   • How many staff are needed per time-slot.
3. Feeds the same data into a SimPy discrete-event simulation that stress-tests
   the plan under stochastic delays and evaluates KPIs.

Key physical layout
───────────────────
  Móttaka  (Reception)   14 spots   – customer drops off car + key
  Gull     (Gold storage) 50 spots  – close to reception
  P3       (Storage)     150 spots  – further away
  Skil     (Delivery)     20 spots  – customer picks up car
"""

__version__ = "0.1.0"
