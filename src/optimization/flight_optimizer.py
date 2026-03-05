"""
Flight Optimization Module using GurobiPy

Implements optimization models for:
- Flight scheduling and slot allocation
- Premium pricing optimization
- Aircraft capacity utilization
- Resource allocation optimization
"""

import logging
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime, timedelta
import numpy as np

try:
    import gurobipy as gp
    from gurobipy import GRB
    GUROBI_AVAILABLE = True
except ImportError:
    GUROBI_AVAILABLE = False
    logging.warning("Gurobi not available, using linear programming approximations")

logger = logging.getLogger(__name__)

class FlightOptimizer:
    """Flight scheduling and pricing optimization using Gurobi"""
    
    def __init__(self):
        self.model = None
        self.ready = GUROBI_AVAILABLE
        
        if not GUROBI_AVAILABLE:
            logger.warning("Gurobi not available, optimization will use approximations")
    
    def is_ready(self) -> bool:
        """Check if optimizer is ready to use"""
        return self.ready
    
    def optimize_schedule(
        self, 
        flights: List[Dict], 
        capacity_constraints: Dict,
        pricing_tiers: Dict
    ) -> Dict[str, Any]:
        """
        Optimize flight scheduling with capacity and pricing considerations
        
        Args:
            flights: List of flight data
            capacity_constraints: Airport capacity limits
            pricing_tiers: Premium and regular pricing tiers
            
        Returns:
            Optimization results including schedule and pricing recommendations
        """
        try:
            if GUROBI_AVAILABLE:
                return self._optimize_with_gurobi(flights, capacity_constraints, pricing_tiers)
            else:
                return self._optimize_approximation(flights, capacity_constraints, pricing_tiers)
        except Exception as e:
            logger.error(f"Optimization failed: {e}")
            return self._fallback_optimization(flights)
    
    def _optimize_with_gurobi(
        self, 
        flights: List[Dict], 
        capacity_constraints: Dict,
        pricing_tiers: Dict
    ) -> Dict[str, Any]:
        """Run full Gurobi optimization"""
        try:
            # Create new model
            model = gp.Model("flight_optimization")
            model.Params.LogToConsole = 0  # Suppress output
            
            n_flights = len(flights)
            n_slots = capacity_constraints.get('total_slots', 48)  # 30min slots in 24h
            
            # Decision variables
            # x[i,t] = 1 if flight i is scheduled in slot t
            x = model.addVars(n_flights, n_slots, vtype=GRB.BINARY, name="schedule")
            
            # p[i] = 1 if flight i uses premium pricing
            p = model.addVars(n_flights, vtype=GRB.BINARY, name="premium")
            
            # Revenue calculation
            base_revenue = {}
            premium_multiplier = pricing_tiers.get('premium_multiplier', 1.5)
            
            for i, flight in enumerate(flights):
                capacity = flight.get('passenger_capacity', 150)
                base_price = self._estimate_base_price(flight)
                base_revenue[i] = capacity * base_price
            
            # Objective: Maximize revenue
            revenue_expr = gp.quicksum(
                x[i, t] * (
                    base_revenue[i] * (1 + p[i] * (premium_multiplier - 1))
                )
                for i in range(n_flights)
                for t in range(n_slots)
            )
            
            model.setObjective(revenue_expr, GRB.MAXIMIZE)
            
            # Constraints
            
            # 1. Each flight scheduled at most once
            for i in range(n_flights):
                model.addConstr(
                    gp.quicksum(x[i, t] for t in range(n_slots)) <= 1,
                    name=f"flight_{i}_once"
                )
            
            # 2. Slot capacity constraints
            runway_capacity = capacity_constraints.get('runway_capacity', 4)
            for t in range(n_slots):
                model.addConstr(
                    gp.quicksum(x[i, t] for i in range(n_flights)) <= runway_capacity,
                    name=f"slot_{t}_capacity"
                )
            
            # 3. Premium slot constraints (limited premium slots)
            premium_slots = capacity_constraints.get('premium_slots', 20)
            model.addConstr(
                gp.quicksum(p[i] * x[i, t] for i in range(n_flights) for t in range(n_slots)) <= premium_slots,
                name="premium_limit"
            )
            
            # 4. Aircraft turnaround constraints
            for i in range(n_flights):
                for j in range(i + 1, n_flights):
                    if self._same_aircraft(flights[i], flights[j]):
                        # Minimum turnaround time (2 slots = 1 hour)
                        for t in range(n_slots - 2):
                            model.addConstr(
                                x[i, t] + gp.quicksum(x[j, s] for s in range(t, min(t + 2, n_slots))) <= 1,
                                name=f"turnaround_{i}_{j}_{t}"
                            )
            
            # Optimize
            model.optimize()
            
            # Extract results
            if model.status == GRB.OPTIMAL:
                scheduled_flights = []
                premium_flights = []
                total_revenue = model.objVal
                
                for i in range(n_flights):
                    for t in range(n_slots):
                        if x[i, t].X > 0.5:  # Scheduled
                            slot_time = datetime.now() + timedelta(minutes=30 * t)
                            scheduled_flights.append({
                                'flight': flights[i],
                                'slot': t,
                                'time': slot_time.isoformat(),
                                'premium': p[i].X > 0.5
                            })
                            
                            if p[i].X > 0.5:
                                premium_flights.append(flights[i]['flight_number'])
                
                return {
                    'status': 'optimal',
                    'total_revenue': total_revenue,
                    'scheduled_flights': scheduled_flights,
                    'premium_flights': premium_flights,
                    'utilization': len(scheduled_flights) / len(flights),
                    'solver': 'gurobi',
                    'solve_time': model.Runtime
                }
            else:
                return {
                    'status': 'infeasible',
                    'message': 'No feasible solution found',
                    'solver': 'gurobi'
                }
                
        except Exception as e:
            logger.error(f"Gurobi optimization error: {e}")
            return self._fallback_optimization(flights)
    
    def _optimize_approximation(
        self, 
        flights: List[Dict], 
        capacity_constraints: Dict,
        pricing_tiers: Dict
    ) -> Dict[str, Any]:
        """Approximation algorithm when Gurobi is not available"""
        logger.info("Running heuristic optimization (Gurobi not available)")
        
        # Simple greedy algorithm
        flights_with_score = []
        
        for i, flight in enumerate(flights):
            # Score based on revenue potential and priority
            capacity = flight.get('passenger_capacity', 150)
            base_price = self._estimate_base_price(flight)
            priority_score = self._calculate_priority(flight)
            
            score = capacity * base_price * priority_score
            flights_with_score.append((score, i, flight))
        
        # Sort by score (descending)
        flights_with_score.sort(reverse=True)
        
        # Allocate slots greedily
        scheduled_flights = []
        premium_flights = []
        slots_used = 0
        max_slots = capacity_constraints.get('total_slots', 48)
        premium_quota = capacity_constraints.get('premium_slots', 20)
        premium_used = 0
        
        for score, i, flight in flights_with_score:
            if slots_used >= max_slots:
                break
                
            # Determine if this should be premium
            is_premium = (
                premium_used < premium_quota and 
                self._should_be_premium(flight, pricing_tiers)
            )
            
            slot_time = datetime.now() + timedelta(minutes=30 * slots_used)
            
            scheduled_flights.append({
                'flight': flight,
                'slot': slots_used,
                'time': slot_time.isoformat(),
                'premium': is_premium
            })
            
            if is_premium:
                premium_flights.append(flight['flight_number'])
                premium_used += 1
            
            slots_used += 1
        
        # Calculate total revenue
        total_revenue = 0
        premium_multiplier = pricing_tiers.get('premium_multiplier', 1.5)
        
        for scheduled in scheduled_flights:
            flight = scheduled['flight']
            capacity = flight.get('passenger_capacity', 150)
            base_price = self._estimate_base_price(flight)
            
            if scheduled['premium']:
                revenue = capacity * base_price * premium_multiplier
            else:
                revenue = capacity * base_price
            
            total_revenue += revenue
        
        return {
            'status': 'heuristic',
            'total_revenue': total_revenue,
            'scheduled_flights': scheduled_flights,
            'premium_flights': premium_flights,
            'utilization': len(scheduled_flights) / len(flights),
            'solver': 'heuristic'
        }
    
    def _fallback_optimization(self, flights: List[Dict]) -> Dict[str, Any]:
        """Simple fallback when optimization fails"""
        scheduled_flights = []
        
        for i, flight in enumerate(flights[:24]):  # Limit to 24 flights
            slot_time = datetime.now() + timedelta(hours=i)
            
            scheduled_flights.append({
                'flight': flight,
                'slot': i,
                'time': slot_time.isoformat(),
                'premium': i % 4 == 0  # Every 4th flight premium
            })
        
        return {
            'status': 'fallback',
            'scheduled_flights': scheduled_flights,
            'premium_flights': [f['flight']['flight_number'] for f in scheduled_flights if f['premium']],
            'solver': 'fallback'
        }
    
    def _estimate_base_price(self, flight: Dict) -> float:
        """Estimate base ticket price"""
        # Simple pricing model based on route and aircraft
        base_price = 200.0  # Base price in USD
        
        # Adjust for aircraft capacity (larger = more efficient)
        capacity = flight.get('passenger_capacity', 150)
        if capacity > 200:
            base_price *= 0.9  # Larger aircraft, lower per-seat cost
        elif capacity < 100:
            base_price *= 1.2  # Smaller aircraft, higher per-seat cost
        
        # Adjust for route (international vs domestic)
        departure = flight.get('departure_airport', '')
        arrival = flight.get('arrival_airport', '')
        
        if departure != arrival and len(departure) == 4 and len(arrival) == 4:
            # International flight
            base_price *= 1.5
        
        return base_price
    
    def _calculate_priority(self, flight: Dict) -> float:
        """Calculate flight priority score"""
        priority = 1.0
        
        # Higher priority for larger aircraft
        capacity = flight.get('passenger_capacity', 150)
        if capacity > 200:
            priority *= 1.3
        elif capacity > 150:
            priority *= 1.1
        
        # Higher priority for certain airlines
        airline = flight.get('airline', '').lower()
        if 'icelandair' in airline:
            priority *= 1.2
        
        return priority
    
    def _should_be_premium(self, flight: Dict, pricing_tiers: Dict) -> bool:
        """Determine if flight should use premium pricing"""
        # Premium criteria
        capacity = flight.get('passenger_capacity', 150)
        
        # Large aircraft or popular routes get premium
        if capacity > 200:
            return True
        
        # International routes
        departure = flight.get('departure_airport', '')
        arrival = flight.get('arrival_airport', '')
        if departure != arrival and len(departure) == 4 and len(arrival) == 4:
            return True
        
        return False
    
    def _same_aircraft(self, flight1: Dict, flight2: Dict) -> bool:
        """Check if two flights use the same aircraft"""
        aircraft1 = flight1.get('aircraft_type', '')
        aircraft2 = flight2.get('aircraft_type', '')
        
        # Simple heuristic: same airline and aircraft type
        airline1 = flight1.get('airline', '')
        airline2 = flight2.get('airline', '')
        
        return aircraft1 == aircraft2 and airline1 == airline2
    
    def optimize_pricing(self, flights: List[Dict], demand_forecast: Dict) -> Dict[str, Any]:
        """
        Optimize pricing based on demand forecast
        """
        try:
            pricing_recommendations = {}
            
            for flight in flights:
                flight_number = flight.get('flight_number', '')
                base_price = self._estimate_base_price(flight)
                
                # Get demand forecast for this flight
                demand = demand_forecast.get(flight_number, 1.0)
                
                # Dynamic pricing based on demand
                if demand > 1.2:
                    recommended_price = base_price * 1.3  # High demand
                elif demand > 0.8:
                    recommended_price = base_price  # Normal demand
                else:
                    recommended_price = base_price * 0.8  # Low demand
                
                pricing_recommendations[flight_number] = {
                    'base_price': base_price,
                    'recommended_price': recommended_price,
                    'demand_factor': demand,
                    'price_adjustment': recommended_price / base_price
                }
            
            return {
                'status': 'success',
                'pricing_recommendations': pricing_recommendations
            }
            
        except Exception as e:
            logger.error(f"Pricing optimization error: {e}")
            return {'status': 'error', 'message': str(e)}