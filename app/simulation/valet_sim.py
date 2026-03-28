"""
SimPy discrete-event simulation of Isavia Premium valet parking operations.

The simulation validates optimization results by stress-testing them under:
  • Stochastic flight delays (customers arrive early/late)
  • Variability in driving times (traffic, weather, human factors)
  • Resource contention (limited staff, parking spaces)
  • Operational disruptions

Key KPIs tracked:
  • Service level: % of cars ready on time
  • Staff utilization: actual vs. planned
  • Zone utilization: occupancy over time
  • Customer wait times: when they arrive early/late
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import numpy as np
import simpy

from app.api.flights import ValetBooking
from app.optimization.valet_optimizer import OptimizationResult
from config import settings

log = logging.getLogger(__name__)


@dataclass
class SimulationResult:
    """Output from the discrete-event simulation."""
    run_id: int
    service_level: float                    # % cars ready on time
    avg_customer_wait_time: float          # minutes (negative = car ready early)
    staff_utilization: Dict[str, float]    # zone → utilization %
    zone_max_occupancy: Dict[str, int]     # zone → peak occupancy
    total_staff_hours_used: float          # actual vs. planned
    violations: List[dict]                 # service failures
    kpi_summary: Dict[str, float]          # aggregated metrics
    
    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "service_level": self.service_level,
            "avg_customer_wait_time": self.avg_customer_wait_time,
            "staff_utilization": self.staff_utilization,
            "zone_max_occupancy": self.zone_max_occupancy,
            "total_staff_hours_used": self.total_staff_hours_used,
            "violations": self.violations,
            "kpi_summary": self.kpi_summary,
        }


@dataclass
class Car:
    """A car in the simulation."""
    booking_id: str
    plate: str
    drop_off_time: float      # simulation time
    pickup_time: float        # simulation time  
    current_zone: Optional[str] = None
    ready_time: Optional[float] = None    # when car reached delivery
    picked_up: bool = False


class ValetSimulation:
    """The main SimPy simulation environment."""
    
    def __init__(self, run_id: int = 0, random_seed: Optional[int] = None):
        self.run_id = run_id
        self.env = simpy.Environment()
        
        # Set random seed for reproducibility
        if random_seed is not None:
            random.seed(random_seed + run_id)
            np.random.seed(random_seed + run_id)
        
        # Resources (staff and parking zones)
        self.staff = simpy.Resource(self.env, capacity=settings.MAX_STAFF)
        self.zones = {
            "reception": simpy.Container(self.env, capacity=settings.CAPACITY_RECEPTION),
            "gull": simpy.Container(self.env, capacity=settings.CAPACITY_GULL), 
            "p3": simpy.Container(self.env, capacity=settings.CAPACITY_P3),
            "delivery": simpy.Container(self.env, capacity=settings.CAPACITY_DELIVERY),
        }
        
        # Tracking
        self.cars = {}
        self.violations = []
        self.staff_events = []  # (time, action, details)
        self.zone_occupancy_log = {zone: [] for zone in self.zones}
        
        # Travel times (with stochastic variation)
        self.base_travel_times = {
            ("reception", "gull"): settings.TRAVEL_RECEPTION_TO_GULL,
            ("reception", "p3"): settings.TRAVEL_RECEPTION_TO_P3,
            ("gull", "delivery"): settings.TRAVEL_GULL_TO_DELIVERY,
            ("p3", "delivery"): settings.TRAVEL_P3_TO_DELIVERY,
            ("delivery", "reception"): settings.TRAVEL_DELIVERY_TO_RECEPTION,
        }
        
        self.base_walk_times = {
            ("gull", "reception"): settings.WALK_GULL_TO_RECEPTION,
            ("p3", "reception"): settings.WALK_P3_TO_RECEPTION,
            ("delivery", "gull"): settings.WALK_DELIVERY_TO_GULL,
            ("delivery", "p3"): settings.WALK_DELIVERY_TO_P3,
        }
    
    def run_simulation(
        self, 
        bookings: List[ValetBooking], 
        plan: OptimizationResult,
        base_time: datetime,
        duration_hours: float = 24.0,
    ) -> SimulationResult:
        """
        Run the simulation with the given plan.
        """
        # Convert bookings to simulation cars with stochastic arrival times
        sim_cars = []
        for booking in bookings:
            # Add noise to customer arrival/pickup times
            drop_noise = np.random.normal(0, 5)  # ±5 min std dev
            pickup_noise = np.random.normal(0, settings.SIM_FLIGHT_DELAY_STD)  # flight delays
            
            drop_sim_time = (booking.departure_time - base_time).total_seconds() / 60 + drop_noise
            pickup_sim_time = (booking.arrival_time - base_time).total_seconds() / 60 + pickup_noise
            
            if drop_sim_time >= 0:  # Only simulate cars that arrive during our horizon
                car = Car(
                    booking_id=booking.booking_id,
                    plate=booking.car_plate,
                    drop_off_time=max(0, drop_sim_time),
                    pickup_time=max(drop_sim_time + 60, pickup_sim_time),  # pickup at least 1h after drop-off
                )
                sim_cars.append(car)
                self.cars[booking.booking_id] = car
        
        # Schedule car arrivals
        for car in sim_cars:
            self.env.process(self._customer_dropoff_process(car))
            self.env.process(self._customer_pickup_process(car))
        
        # Schedule planned moves from optimization
        for move in plan.car_movements:
            if move["car"] in self.cars:
                move_time = (datetime.fromisoformat(move["time"]) - base_time).total_seconds() / 60
                if move_time >= 0:
                    self.env.process(self._scheduled_move_process(
                        move["car"], 
                        move["from_zone"], 
                        move["to_zone"], 
                        move_time
                    ))
        
        # Run simulation
        self.env.run(until=duration_hours * 60)  # convert to minutes
        
        return self._analyze_results()
    
    def _customer_dropoff_process(self, car: Car):
        """Customer arrives and drops off their car."""
        yield self.env.timeout(car.drop_off_time)
        
        # Customer parks at reception
        try:
            self.zones["reception"].put(1)
            car.current_zone = "reception"
            log.debug("Car %s dropped off at reception (t=%.1f)", car.booking_id, self.env.now)
        except simpy.Interrupt:
            # Reception full — this is a constraint violation
            self.violations.append({
                "time": self.env.now,
                "type": "reception_overflow", 
                "car": car.booking_id,
                "message": "Reception area full when customer arrived"
            })
    
    def _customer_pickup_process(self, car: Car):
        """Customer returns and expects their car."""
        yield self.env.timeout(car.pickup_time)
        
        # Customer expects car to be at delivery
        if car.current_zone == "delivery" and car.ready_time is not None:
            # Success: car is ready
            wait_time = max(0, self.env.now - car.ready_time)  # how long car waited
            car.picked_up = True
            self.zones["delivery"].get(1)  # remove from delivery
            log.debug("Car %s picked up successfully (wait=%.1f min)", car.booking_id, wait_time)
        else:
            # Violation: car not ready
            self.violations.append({
                "time": self.env.now,
                "type": "car_not_ready",
                "car": car.booking_id,
                "current_zone": car.current_zone,
                "message": f"Car in {car.current_zone}, not delivery"
            })
            log.warning("Car %s not ready for pickup at t=%.1f", car.booking_id, self.env.now)
    
    def _scheduled_move_process(self, car_id: str, from_zone: str, to_zone: str, scheduled_time: float):
        """Execute a planned car move."""
        yield self.env.timeout(scheduled_time)
        
        car = self.cars.get(car_id)
        if not car:
            log.warning("Cannot move car %s: booking not found", car_id)
            return

        # If the car hasn't arrived at the expected source zone yet, wait up to 60 min
        wait_limit = 60
        waited = 0
        while car.current_zone != from_zone and waited < wait_limit:
            yield self.env.timeout(1)
            waited += 1

        if car.current_zone != from_zone:
            log.warning("Cannot move car %s: not in %s at t=%.1f (is in %s)",
                        car_id, from_zone, self.env.now, car.current_zone)
            return
        
        # Request staff
        with self.staff.request() as staff_req:
            yield staff_req
            
            staff_start_time = self.env.now
            self.staff_events.append((self.env.now, "start_move", {"car": car_id, "from": from_zone, "to": to_zone}))
            
            # Remove car from source zone
            try:
                self.zones[from_zone].get(1)
            except ValueError:
                log.error("Car %s not actually in %s", car_id, from_zone)
                return
            
            # Drive car (with stochastic delay)
            base_time = self.base_travel_times.get((from_zone, to_zone), 5)
            actual_time = max(1, np.random.normal(base_time, base_time * settings.SIM_DRIVE_TIME_STD))
            yield self.env.timeout(actual_time)
            
            # Place car in destination zone
            try:
                self.zones[to_zone].put(1)
                car.current_zone = to_zone
                
                if to_zone == "delivery":
                    car.ready_time = self.env.now  # car is now ready for pickup
                
                log.debug("Moved car %s: %s → %s (took %.1f min)", car_id, from_zone, to_zone, actual_time)
            except simpy.Interrupt:
                # Destination zone full
                self.violations.append({
                    "time": self.env.now,
                    "type": "zone_overflow",
                    "car": car_id,
                    "zone": to_zone,
                    "message": f"{to_zone} zone full during move"
                })
                # Put car back in source (emergency)
                self.zones[from_zone].put(1)
                car.current_zone = from_zone
            
            # Staff walks back (if needed)
            walk_time = self.base_walk_times.get((to_zone, from_zone), 0)
            if walk_time > 0:
                actual_walk = max(0, np.random.normal(walk_time, walk_time * 0.2))
                yield self.env.timeout(actual_walk)
            
            staff_end_time = self.env.now
            total_staff_time = staff_end_time - staff_start_time
            self.staff_events.append((self.env.now, "end_move", {"car": car_id, "duration": total_staff_time}))
    
    def _analyze_results(self) -> SimulationResult:
        """Analyze simulation results and compute KPIs."""
        total_cars = len(self.cars)
        if total_cars == 0:
            return SimulationResult(
                run_id=self.run_id,
                service_level=0,
                avg_customer_wait_time=0,
                staff_utilization={},
                zone_max_occupancy={},
                total_staff_hours_used=0,
                violations=[],
                kpi_summary={}
            )
        
        # Service level: % cars ready on time
        cars_ready_on_time = sum(1 for car in self.cars.values() 
                                if car.picked_up or (car.ready_time and car.ready_time <= car.pickup_time))
        service_level = cars_ready_on_time / total_cars * 100
        
        # Customer wait times
        wait_times = []
        for car in self.cars.values():
            if car.ready_time and car.pickup_time:
                wait = car.ready_time - car.pickup_time  # negative = car ready early (good)
                wait_times.append(wait)
        avg_wait = float(np.mean(wait_times)) if wait_times else 0.0

        # Staff utilization (simplified)
        total_staff_time = sum(event[2].get("duration", 0) for event in self.staff_events if event[1] == "end_move")
        total_staff_hours_used = float(total_staff_time) / 60.0

        # Zone max occupancy (approximation)
        zone_max_occupancy = {}
        for zone_name, container in self.zones.items():
            zone_max_occupancy[zone_name] = int(container.capacity - container.level)

        # KPI summary
        kpi_summary = {
            "service_level_pct": float(service_level),
            "avg_wait_time_min": float(avg_wait),
            "total_violations": int(len(self.violations)),
            "staff_hours_used": float(total_staff_hours_used),
        }

        return SimulationResult(
            run_id=int(self.run_id),
            service_level=float(service_level),
            avg_customer_wait_time=float(avg_wait),
            staff_utilization={"overall": float(min(100, total_staff_hours_used / (settings.MAX_STAFF * 24) * 100))},
            zone_max_occupancy=zone_max_occupancy,
            total_staff_hours_used=float(total_staff_hours_used),
            violations=self.violations,
            kpi_summary=kpi_summary
        )


def _f(v) -> float:
    """Convert numpy scalar to plain Python float for JSON serialisation."""
    return float(v)


def run_monte_carlo_simulation(
    bookings: List[ValetBooking],
    plan: OptimizationResult, 
    base_time: datetime,
    n_runs: int = None,
    duration_hours: float = 24.0,
) -> Dict[str, any]:
    """
    Run multiple simulation runs to get statistical results.
    """
    n_runs = n_runs or settings.SIM_RUNS
    results = []
    
    for run_id in range(n_runs):
        sim = ValetSimulation(run_id=run_id, random_seed=settings.SIM_RANDOM_SEED)
        result = sim.run_simulation(bookings, plan, base_time, duration_hours)
        results.append(result)
    
    # Aggregate results
    if not results:
        return {"status": "error", "message": "No simulation results"}
    
    service_levels = [r.service_level for r in results]
    wait_times = [r.avg_customer_wait_time for r in results]
    staff_hours = [r.total_staff_hours_used for r in results]
    violation_counts = [len(r.violations) for r in results]
    
    aggregated = {
        "status": "completed",
        "n_runs": n_runs,
        "results": [r.to_dict() for r in results],
        "summary": {
            "service_level": {
                "mean": _f(np.mean(service_levels)),
                "std":  _f(np.std(service_levels)),
                "min":  _f(np.min(service_levels)),
                "max":  _f(np.max(service_levels)),
                "p95":  _f(np.percentile(service_levels, 95)),
            },
            "avg_wait_time": {
                "mean": _f(np.mean(wait_times)),
                "std":  _f(np.std(wait_times)),
                "min":  _f(np.min(wait_times)),
                "max":  _f(np.max(wait_times)),
            },
            "staff_hours": {
                "mean": _f(np.mean(staff_hours)),
                "std":  _f(np.std(staff_hours)),
                "min":  _f(np.min(staff_hours)),
                "max":  _f(np.max(staff_hours)),
            },
            "violations": {
                "mean":              _f(np.mean(violation_counts)),
                "std":               _f(np.std(violation_counts)),
                "max":               _f(np.max(violation_counts)),
                "total_across_runs": int(sum(violation_counts)),
            }
        },
        "recommendations": _generate_recommendations(results)
    }

    return aggregated


def _generate_recommendations(results: List[SimulationResult]) -> List[str]:
    """Generate operational recommendations based on simulation results."""
    recommendations = []
    
    avg_service_level = np.mean([r.service_level for r in results])
    avg_violations = np.mean([len(r.violations) for r in results])
    
    if avg_service_level < 95:
        recommendations.append(f"Service level ({avg_service_level:.1f}%) below target. Consider adding staff or adjusting lead times.")
    
    if avg_violations > 2:
        recommendations.append(f"Average {avg_violations:.1f} violations per run. Review capacity constraints and scheduling.")
    
    # Check for specific violation types
    violation_types = {}
    for result in results:
        for violation in result.violations:
            vtype = violation["type"]
            violation_types[vtype] = violation_types.get(vtype, 0) + 1
    
    if violation_types.get("reception_overflow", 0) > 0:
        recommendations.append("Reception area overflow detected. Consider expanding capacity or staggering arrivals.")
    
    if violation_types.get("car_not_ready", 0) > 0:
        recommendations.append("Cars not ready for pickup. Increase delivery lead time or optimize move scheduling.")
    
    if not recommendations:
        recommendations.append("Operations performing well within targets.")
    
    return recommendations