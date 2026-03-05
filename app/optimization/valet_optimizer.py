"""
GurobiPy optimization model for Isavia Premium valet parking.

The core problem:
  • Customer drops car at Reception at known time
  • Car must be at Delivery ≥15 minutes before customer returns
  • Minimize total staff-time while meeting all constraints
  • Capacity limits: Reception(14), Gull(50), P3(150), Delivery(20)

Decision variables:
  • x[car,zone,t] = 1 if car is in zone at time t
  • move[car,from_zone,to_zone,t] = 1 if car moves from→to starting at time t  
  • staff[t] = number of staff working at time t

Constraints:
  • Flow conservation: cars can only be in one place at a time
  • Capacity limits for each zone
  • Cars must reach delivery by deadline
  • Staff must be sufficient to handle all moves in each time period
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np

# GurobiPy — fallback to simple heuristics if not available
try:
    import gurobipy as gp
    from gurobipy import GRB
    GUROBI_AVAILABLE = True
except ImportError:
    GUROBI_AVAILABLE = False

from app.api.flights import ValetBooking
from config import settings

log = logging.getLogger(__name__)


@dataclass 
class OptimizationResult:
    """Output from the optimization model."""
    status: str                           # "optimal", "infeasible", "heuristic", "error"
    total_staff_hours: float             # objective value
    staff_schedule: Dict[int, int]       # time_slot → staff_count
    car_movements: List[dict]            # list of {car, from_zone, to_zone, time_slot}
    zone_occupancy: Dict[str, Dict[int, int]]  # zone → time_slot → car_count
    solve_time_seconds: float = 0.0
    solver_used: str = "unknown"
    
    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "total_staff_hours": self.total_staff_hours,
            "staff_schedule": self.staff_schedule,
            "car_movements": self.car_movements,
            "zone_occupancy": self.zone_occupancy,
            "solve_time_seconds": self.solve_time_seconds,
            "solver_used": self.solver_used,
        }


class ValetOptimizer:
    """The main optimization engine."""
    
    def __init__(self):
        self.zones = ["reception", "gull", "p3", "delivery"] 
        self.capacities = {
            "reception": settings.CAPACITY_RECEPTION,
            "gull": settings.CAPACITY_GULL, 
            "p3": settings.CAPACITY_P3,
            "delivery": settings.CAPACITY_DELIVERY,
        }
        
        # Travel times between zones (minutes)
        self.travel_times = {
            ("reception", "gull"): settings.TRAVEL_RECEPTION_TO_GULL,
            ("reception", "p3"): settings.TRAVEL_RECEPTION_TO_P3,
            ("gull", "delivery"): settings.TRAVEL_GULL_TO_DELIVERY,
            ("p3", "delivery"): settings.TRAVEL_P3_TO_DELIVERY,
            ("delivery", "reception"): settings.TRAVEL_DELIVERY_TO_RECEPTION,
        }
        
        # Return walking times (staff walks back without car)
        self.walk_times = {
            ("gull", "reception"): settings.WALK_GULL_TO_RECEPTION,
            ("p3", "reception"): settings.WALK_P3_TO_RECEPTION,
            ("delivery", "gull"): settings.WALK_DELIVERY_TO_GULL,
            ("delivery", "p3"): settings.WALK_DELIVERY_TO_P3,
        }
    
    def optimize(self, bookings: List[ValetBooking], base_time: datetime) -> OptimizationResult:
        """
        Main entry point: optimize the valet operation.
        """
        if GUROBI_AVAILABLE:
            return self._optimize_with_gurobi(bookings, base_time)
        else:
            log.warning("Gurobi not available, falling back to heuristic")
            return self._optimize_heuristic(bookings, base_time)
    
    def _optimize_with_gurobi(self, bookings: List[ValetBooking], base_time: datetime) -> OptimizationResult:
        """Solve using Gurobi MIP solver."""
        try:
            model = gp.Model("valet_parking")
            model.Params.LogToConsole = 0  # Suppress solver output
            model.Params.TimeLimit = 300   # 5 minute time limit
            
            # ── Time discretization ──
            slot_minutes = settings.TIME_SLOT_MINUTES  
            horizon_minutes = settings.PLANNING_HORIZON_H * 60
            n_slots = math.ceil(horizon_minutes / slot_minutes)
            
            def time_to_slot(dt: datetime) -> int:
                """Convert datetime to time slot index."""
                minutes_from_base = (dt - base_time).total_seconds() / 60
                return max(0, min(n_slots - 1, int(minutes_from_base / slot_minutes)))
            
            # ── Decision variables ──
            n_cars = len(bookings)
            
            # x[car, zone, t] = 1 if car is in zone at time t
            x = model.addVars(n_cars, self.zones, n_slots, vtype=GRB.BINARY, name="location")
            
            # move[car, from_zone, to_zone, t] = 1 if move starts at time t
            moves = {}
            for i in range(n_cars):
                for from_z in self.zones:
                    for to_z in self.zones:
                        if from_z != to_z and self._is_valid_move(from_z, to_z):
                            moves[i, from_z, to_z] = model.addVars(
                                n_slots, vtype=GRB.BINARY, name=f"move_{i}_{from_z}_{to_z}"
                            )
            
            # staff[t] = number of staff required at time t
            staff = model.addVars(n_slots, vtype=GRB.INTEGER, name="staff")
            
            # ── Objective: minimize total staff-hours ──
            obj_expr = gp.quicksum(staff[t] * (slot_minutes / 60.0) for t in range(n_slots))
            model.setObjective(obj_expr, GRB.MINIMIZE)
            
            # ── Constraints ──
            
            # 1. Each car starts at reception when customer drops it off
            for i, booking in enumerate(bookings):
                drop_slot = time_to_slot(booking.departure_time)
                if drop_slot < n_slots:
                    model.addConstr(x[i, "reception", drop_slot] == 1, name=f"car_{i}_arrival")
            
            # 2. Each car must be at delivery by deadline
            for i, booking in enumerate(bookings):
                deadline = booking.arrival_time - timedelta(minutes=settings.DELIVERY_LEAD_TIME)
                deadline_slot = time_to_slot(deadline)
                if deadline_slot < n_slots:
                    model.addConstr(x[i, "delivery", deadline_slot] == 1, name=f"car_{i}_deadline")
            
            # 3. Flow conservation: car can only be in one zone at a time
            for i in range(n_cars):
                for t in range(n_slots):
                    model.addConstr(
                        gp.quicksum(x[i, z, t] for z in self.zones) <= 1,
                        name=f"flow_{i}_{t}"
                    )
            
            # 4. Movement logic: if car moves from A→B at time t, then x[A,t]=1 and x[B,t+travel_time]=1
            for i in range(n_cars):
                for from_z in self.zones:
                    for to_z in self.zones:
                        if (i, from_z, to_z) not in moves:
                            continue
                        
                        travel_slots = math.ceil(self.travel_times.get((from_z, to_z), 0) / slot_minutes)
                        
                        for t in range(n_slots - travel_slots):
                            # If move starts at t, car must be in from_z at t
                            model.addConstr(
                                moves[i, from_z, to_z][t] <= x[i, from_z, t],
                                name=f"move_from_{i}_{from_z}_{to_z}_{t}"
                            )
                            
                            # And car must be in to_z at t + travel_time
                            arrival_slot = min(t + travel_slots, n_slots - 1)
                            model.addConstr(
                                moves[i, from_z, to_z][t] <= x[i, to_z, arrival_slot],
                                name=f"move_to_{i}_{from_z}_{to_z}_{t}"
                            )
            
            # 5. Capacity constraints
            for zone in self.zones:
                for t in range(n_slots):
                    model.addConstr(
                        gp.quicksum(x[i, zone, t] for i in range(n_cars)) <= self.capacities[zone],
                        name=f"capacity_{zone}_{t}"
                    )
            
            # 6. Staff requirements: must have enough staff to handle all moves
            for t in range(n_slots):
                total_move_time = 0
                for i in range(n_cars):
                    for from_z in self.zones:
                        for to_z in self.zones:
                            if (i, from_z, to_z) in moves:
                                move_duration = (
                                    self.travel_times.get((from_z, to_z), 0) +
                                    self.walk_times.get((to_z, from_z), 0)
                                )
                                total_move_time += moves[i, from_z, to_z][t] * move_duration
                
                # Convert to staff-slots needed
                staff_slots_needed = total_move_time / slot_minutes
                model.addConstr(staff[t] >= staff_slots_needed, name=f"staff_{t}")
                model.addConstr(staff[t] <= settings.MAX_STAFF, name=f"staff_max_{t}")
            
            # ── Solve ──
            model.optimize()
            
            if model.Status == GRB.OPTIMAL:
                return self._extract_gurobi_solution(model, x, moves, staff, bookings, base_time, slot_minutes)
            elif model.Status == GRB.INFEASIBLE:
                return OptimizationResult(
                    status="infeasible",
                    total_staff_hours=float('inf'),
                    staff_schedule={},
                    car_movements=[],
                    zone_occupancy={},
                    solve_time_seconds=model.Runtime,
                    solver_used="gurobi"
                )
            else:
                # Time limit, suboptimal, etc.
                if model.SolCount > 0:
                    return self._extract_gurobi_solution(model, x, moves, staff, bookings, base_time, slot_minutes)
                else:
                    return OptimizationResult(
                        status="error",
                        total_staff_hours=float('inf'),
                        staff_schedule={},
                        car_movements=[],
                        zone_occupancy={},
                        solve_time_seconds=model.Runtime,
                        solver_used="gurobi"
                    )
                    
        except Exception as e:
            log.error("Gurobi optimization failed: %s", e)
            return OptimizationResult(
                status="error",
                total_staff_hours=0,
                staff_schedule={},
                car_movements=[],
                zone_occupancy={},
                solver_used="gurobi_error"
            )
    
    def _extract_gurobi_solution(self, model, x, moves, staff, bookings, base_time, slot_minutes) -> OptimizationResult:
        """Extract solution from solved Gurobi model."""
        n_slots = len(staff)
        
        # Staff schedule
        staff_schedule = {}
        for t in range(n_slots):
            if staff[t].X > 0.5:
                staff_schedule[t] = int(round(staff[t].X))
        
        # Car movements
        car_movements = []
        for i in range(len(bookings)):
            for from_z in self.zones:
                for to_z in self.zones:
                    if (i, from_z, to_z) in moves:
                        for t in range(n_slots):
                            if moves[i, from_z, to_z][t].X > 0.5:
                                move_time = base_time + timedelta(minutes=t * slot_minutes)
                                car_movements.append({
                                    "car": bookings[i].booking_id,
                                    "from_zone": from_z,
                                    "to_zone": to_z,
                                    "time_slot": t,
                                    "time": move_time.isoformat(),
                                })
        
        # Zone occupancy
        zone_occupancy = {}
        for zone in self.zones:
            zone_occupancy[zone] = {}
            for t in range(n_slots):
                count = sum(1 for i in range(len(bookings)) if x[i, zone, t].X > 0.5)
                if count > 0:
                    zone_occupancy[zone][t] = count
        
        return OptimizationResult(
            status="optimal",
            total_staff_hours=model.ObjVal,
            staff_schedule=staff_schedule,
            car_movements=car_movements,
            zone_occupancy=zone_occupancy,
            solve_time_seconds=model.Runtime,
            solver_used="gurobi"
        )
    
    def _optimize_heuristic(self, bookings: List[ValetBooking], base_time: datetime) -> OptimizationResult:
        """
        Simple heuristic when Gurobi is not available:
        - Send cars to Gull if possible (closer), otherwise P3
        - Move to delivery just in time to meet deadline
        - Estimate staff requirements
        """
        slot_minutes = settings.TIME_SLOT_MINUTES
        horizon_minutes = settings.PLANNING_HORIZON_H * 60
        n_slots = math.ceil(horizon_minutes / slot_minutes)
        
        def time_to_slot(dt: datetime) -> int:
            minutes_from_base = (dt - base_time).total_seconds() / 60
            return max(0, min(n_slots - 1, int(minutes_from_base / slot_minutes)))
        
        # Simple assignment: prefer Gull, fall back to P3
        car_assignments = {}  # car_id → storage_zone
        gull_usage = [0] * n_slots
        p3_usage = [0] * n_slots
        
        staff_schedule = {}
        car_movements = []
        
        for booking in bookings:
            car_id = booking.booking_id
            drop_slot = time_to_slot(booking.departure_time)
            deadline = booking.arrival_time - timedelta(minutes=settings.DELIVERY_LEAD_TIME)
            deadline_slot = time_to_slot(deadline)
            
            if drop_slot >= n_slots or deadline_slot >= n_slots:
                continue  # Outside planning horizon
            
            # Try to assign to Gull first
            storage_zone = "gull"
            if gull_usage[drop_slot] >= settings.CAPACITY_GULL:
                storage_zone = "p3"
                if p3_usage[drop_slot] >= settings.CAPACITY_P3:
                    log.warning("Capacity exceeded for car %s", car_id)
                    continue
            
            car_assignments[car_id] = storage_zone
            
            # Update usage
            if storage_zone == "gull":
                for t in range(drop_slot, deadline_slot):
                    if t < n_slots:
                        gull_usage[t] += 1
            else:
                for t in range(drop_slot, deadline_slot):
                    if t < n_slots:
                        p3_usage[t] += 1
            
            # Schedule moves
            # 1. Reception → Storage
            car_movements.append({
                "car": car_id,
                "from_zone": "reception",
                "to_zone": storage_zone,
                "time_slot": drop_slot,
                "time": (base_time + timedelta(minutes=drop_slot * slot_minutes)).isoformat(),
            })
            
            # 2. Storage → Delivery (just in time)
            move_to_delivery_slot = max(0, deadline_slot - 1)
            car_movements.append({
                "car": car_id,
                "from_zone": storage_zone, 
                "to_zone": "delivery",
                "time_slot": move_to_delivery_slot,
                "time": (base_time + timedelta(minutes=move_to_delivery_slot * slot_minutes)).isoformat(),
            })
        
        # Estimate staff per slot (simplified)
        moves_per_slot = {}
        for move in car_movements:
            slot = move["time_slot"]
            moves_per_slot[slot] = moves_per_slot.get(slot, 0) + 1
        
        for slot, move_count in moves_per_slot.items():
            staff_schedule[slot] = min(settings.MAX_STAFF, max(1, move_count))
        
        # Calculate zone occupancy
        zone_occupancy = {
            "reception": {},
            "gull": {t: count for t, count in enumerate(gull_usage) if count > 0},
            "p3": {t: count for t, count in enumerate(p3_usage) if count > 0},
            "delivery": {},
        }
        
        total_staff_hours = sum(staff_count * (slot_minutes / 60.0) for staff_count in staff_schedule.values())
        
        return OptimizationResult(
            status="heuristic",
            total_staff_hours=total_staff_hours,
            staff_schedule=staff_schedule,
            car_movements=car_movements,
            zone_occupancy=zone_occupancy,
            solver_used="heuristic"
        )
    
    def _is_valid_move(self, from_zone: str, to_zone: str) -> bool:
        """Check if a move between zones is physically possible."""
        valid_moves = {
            "reception": ["gull", "p3"],
            "gull": ["delivery"],
            "p3": ["delivery"],
            "delivery": ["reception"]  # staff returns empty-handed
        }
        return to_zone in valid_moves.get(from_zone, [])