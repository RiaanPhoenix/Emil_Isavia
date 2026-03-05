"""
Airport Operations Simulation using SimPy

Simulates:
- Passenger flow through airport
- Aircraft ground operations
- Runway operations and delays
- Resource utilization (gates, staff, equipment)
- Turnaround times and bottlenecks
"""

import simpy
import random
import logging
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
import numpy as np
from collections import defaultdict, deque
import json

logger = logging.getLogger(__name__)

class AirportSimulator:
    """Airport operations discrete event simulation"""
    
    def __init__(self):
        self.env = None
        self.stats = defaultdict(list)
        self.ready = True
    
    def is_ready(self) -> bool:
        """Check if simulator is ready"""
        return self.ready
    
    def run_simulation(
        self, 
        flights: List[Dict], 
        airport_config: Dict,
        duration: float = 24.0
    ) -> Dict[str, Any]:
        """
        Run airport operations simulation
        
        Args:
            flights: List of flight data
            airport_config: Airport configuration (gates, runways, staff)
            duration: Simulation duration in hours
            
        Returns:
            Simulation results and statistics
        """
        try:
            logger.info(f"Starting airport simulation for {duration} hours")
            
            # Initialize simulation environment
            self.env = simpy.Environment()
            self.stats = defaultdict(list)
            
            # Create airport resources
            resources = self._create_resources(airport_config)
            
            # Create flight processes
            for flight in flights:
                self.env.process(self._flight_process(flight, resources))
            
            # Run simulation
            self.env.run(until=duration * 60)  # Convert hours to minutes
            
            # Analyze results
            results = self._analyze_results(duration)
            
            logger.info("Airport simulation completed")
            return results
            
        except Exception as e:
            logger.error(f"Simulation error: {e}")
            return {
                'status': 'error',
                'message': str(e),
                'timestamp': datetime.now().isoformat()
            }
    
    def _create_resources(self, config: Dict) -> Dict[str, Any]:
        """Create airport resources"""
        resources = {
            # Runways
            'runways': simpy.Resource(
                self.env, 
                capacity=config.get('runways', 2)
            ),
            
            # Gates
            'gates': simpy.Resource(
                self.env, 
                capacity=config.get('gates', 12)
            ),
            
            # Check-in counters
            'checkin': simpy.Resource(
                self.env, 
                capacity=config.get('checkin_counters', 8)
            ),
            
            # Security checkpoints
            'security': simpy.Resource(
                self.env, 
                capacity=config.get('security_lanes', 4)
            ),
            
            # Baggage handling
            'baggage': simpy.Resource(
                self.env, 
                capacity=config.get('baggage_belts', 6)
            ),
            
            # Ground crew
            'ground_crew': simpy.Resource(
                self.env, 
                capacity=config.get('ground_crew_teams', 10)
            ),
            
            # Fuel trucks
            'fuel_trucks': simpy.Resource(
                self.env, 
                capacity=config.get('fuel_trucks', 4)
            ),
            
            # Catering trucks
            'catering': simpy.Resource(
                self.env, 
                capacity=config.get('catering_trucks', 3)
            )
        }
        
        return resources
    
    def _flight_process(self, flight: Dict, resources: Dict):
        """Main flight process simulation"""
        flight_number = flight.get('flight_number', 'Unknown')
        arrival_time = self._parse_time(flight.get('departure_time'))
        capacity = flight.get('passenger_capacity', 150)
        
        logger.debug(f"Processing flight {flight_number}")
        
        # Wait until flight arrival time
        if arrival_time > 0:
            yield self.env.timeout(arrival_time)
        
        # Record flight start
        start_time = self.env.now
        self.stats['flight_arrivals'].append({
            'flight': flight_number,
            'time': start_time,
            'capacity': capacity
        })
        
        # Gate assignment
        with resources['gates'].request() as gate_req:
            yield gate_req
            gate_start = self.env.now
            
            # Ground operations
            yield self.env.process(self._ground_operations(flight, resources))
            
            # Passenger processes (if departure)
            if flight.get('departure_airport') == 'BIKF':  # Departing from our airport
                yield self.env.process(self._passenger_departure_process(flight, resources))
            
            # Gate hold time
            gate_time = random.uniform(30, 90)  # 30-90 minutes
            yield self.env.timeout(gate_time)
            
            gate_end = self.env.now
            
            self.stats['gate_utilization'].append({
                'flight': flight_number,
                'start': gate_start,
                'end': gate_end,
                'duration': gate_end - gate_start
            })
        
        # Runway operations
        with resources['runways'].request() as runway_req:
            yield runway_req
            runway_start = self.env.now
            
            # Takeoff/landing time
            runway_time = random.uniform(2, 5)  # 2-5 minutes
            yield self.env.timeout(runway_time)
            
            runway_end = self.env.now
            
            self.stats['runway_operations'].append({
                'flight': flight_number,
                'start': runway_start,
                'end': runway_end,
                'duration': runway_end - runway_start,
                'type': 'departure' if flight.get('departure_airport') == 'BIKF' else 'arrival'
            })
        
        # Record flight completion
        total_time = self.env.now - start_time
        self.stats['flight_completions'].append({
            'flight': flight_number,
            'start': start_time,
            'end': self.env.now,
            'total_time': total_time
        })
    
    def _ground_operations(self, flight: Dict, resources: Dict):
        """Ground operations for aircraft"""
        operations = []
        
        # Baggage handling
        baggage_process = self.env.process(
            self._resource_operation(resources['baggage'], 15, 30, 'baggage')
        )
        operations.append(baggage_process)
        
        # Fueling
        fuel_process = self.env.process(
            self._resource_operation(resources['fuel_trucks'], 20, 40, 'fuel')
        )
        operations.append(fuel_process)
        
        # Catering
        catering_process = self.env.process(
            self._resource_operation(resources['catering'], 10, 25, 'catering')
        )
        operations.append(catering_process)
        
        # Ground crew cleaning/maintenance
        cleaning_process = self.env.process(
            self._resource_operation(resources['ground_crew'], 15, 35, 'cleaning')
        )
        operations.append(cleaning_process)
        
        # Wait for all operations to complete
        yield simpy.events.AllOf(self.env, operations)
    
    def _resource_operation(self, resource, min_time: float, max_time: float, operation_type: str):
        """Generic resource operation"""
        with resource.request() as req:
            yield req
            operation_time = random.uniform(min_time, max_time)
            yield self.env.timeout(operation_time)
            
            self.stats[f'{operation_type}_operations'].append({
                'start': self.env.now - operation_time,
                'duration': operation_time
            })
    
    def _passenger_departure_process(self, flight: Dict, resources: Dict):
        """Simulate passenger departure processes"""
        capacity = flight.get('passenger_capacity', 150)
        load_factor = random.uniform(0.6, 0.95)  # 60-95% load factor
        num_passengers = int(capacity * load_factor)
        
        # Check-in process
        checkin_process = self.env.process(
            self._passenger_checkin(num_passengers, resources['checkin'])
        )
        
        # Security process
        security_process = self.env.process(
            self._passenger_security(num_passengers, resources['security'])
        )
        
        # Wait for passenger processes
        yield checkin_process
        yield security_process
        
        # Boarding
        boarding_time = max(15, num_passengers * 0.5)  # Boarding time estimation
        yield self.env.timeout(boarding_time)
        
        self.stats['passenger_boardings'].append({
            'flight': flight.get('flight_number'),
            'passengers': num_passengers,
            'boarding_time': boarding_time
        })
    
    def _passenger_checkin(self, num_passengers: int, checkin_resource):
        """Check-in process simulation"""
        # Passengers arrive over time
        arrival_window = 120  # 2 hours before flight
        
        for i in range(num_passengers):
            # Stagger passenger arrivals
            arrival_delay = random.uniform(0, arrival_window)
            yield self.env.timeout(arrival_delay / num_passengers)
            
            # Check-in process
            with checkin_resource.request() as req:
                yield req
                checkin_time = random.uniform(2, 8)  # 2-8 minutes per passenger
                yield self.env.timeout(checkin_time)
    
    def _passenger_security(self, num_passengers: int, security_resource):
        """Security screening simulation"""
        for i in range(num_passengers):
            with security_resource.request() as req:
                yield req
                security_time = random.uniform(1, 4)  # 1-4 minutes per passenger
                yield self.env.timeout(security_time)
                
                # Small chance of additional screening
                if random.random() < 0.05:  # 5% chance
                    additional_time = random.uniform(5, 15)
                    yield self.env.timeout(additional_time)
    
    def _parse_time(self, time_str: Optional[str]) -> float:
        """Parse time string to simulation time (minutes from start)"""
        if not time_str:
            return random.uniform(0, 1440)  # Random time in 24 hours
        
        try:
            # Simple parsing - assume ISO format
            dt = datetime.fromisoformat(time_str.replace('Z', '+00:00'))
            now = datetime.now()
            diff = (dt - now).total_seconds() / 60  # Minutes
            return max(0, diff)
        except:
            return random.uniform(0, 1440)
    
    def _analyze_results(self, duration: float) -> Dict[str, Any]:
        """Analyze simulation results and generate statistics"""
        results = {
            'status': 'completed',
            'simulation_duration': duration,
            'timestamp': datetime.now().isoformat()
        }
        
        # Flight statistics
        total_flights = len(self.stats['flight_completions'])
        results['flight_statistics'] = {
            'total_flights': total_flights,
            'flights_per_hour': total_flights / duration if duration > 0 else 0
        }
        
        if self.stats['flight_completions']:
            turnaround_times = [f['total_time'] for f in self.stats['flight_completions']]
            results['flight_statistics'].update({
                'average_turnaround': np.mean(turnaround_times),
                'max_turnaround': np.max(turnaround_times),
                'min_turnaround': np.min(turnaround_times)
            })
        
        # Runway statistics
        if self.stats['runway_operations']:
            runway_ops = self.stats['runway_operations']
            runway_times = [op['duration'] for op in runway_ops]
            
            results['runway_statistics'] = {
                'total_operations': len(runway_ops),
                'operations_per_hour': len(runway_ops) / duration,
                'average_operation_time': np.mean(runway_times),
                'departures': len([op for op in runway_ops if op.get('type') == 'departure']),
                'arrivals': len([op for op in runway_ops if op.get('type') == 'arrival'])
            }
        
        # Gate utilization
        if self.stats['gate_utilization']:
            gate_ops = self.stats['gate_utilization']
            gate_times = [op['duration'] for op in gate_ops]
            
            results['gate_statistics'] = {
                'total_gate_hours': sum(gate_times) / 60,
                'average_gate_time': np.mean(gate_times),
                'utilization_rate': (sum(gate_times) / 60) / (duration * 12)  # Assuming 12 gates
            }
        
        # Passenger statistics
        if self.stats['passenger_boardings']:
            passenger_ops = self.stats['passenger_boardings']
            total_passengers = sum(op['passengers'] for op in passenger_ops)
            boarding_times = [op['boarding_time'] for op in passenger_ops]
            
            results['passenger_statistics'] = {
                'total_passengers': total_passengers,
                'passengers_per_hour': total_passengers / duration,
                'average_boarding_time': np.mean(boarding_times),
                'flights_with_passengers': len(passenger_ops)
            }
        
        # Resource utilization summary
        results['resource_utilization'] = {}
        
        for resource_type in ['baggage_operations', 'fuel_operations', 'catering_operations', 'cleaning_operations']:
            if self.stats[resource_type]:
                operations = self.stats[resource_type]
                total_time = sum(op['duration'] for op in operations)
                results['resource_utilization'][resource_type] = {
                    'total_operations': len(operations),
                    'total_time_hours': total_time / 60,
                    'average_operation_time': np.mean([op['duration'] for op in operations])
                }
        
        # Bottleneck analysis
        results['bottlenecks'] = self._identify_bottlenecks()
        
        # Recommendations
        results['recommendations'] = self._generate_recommendations(results)
        
        return results
    
    def _identify_bottlenecks(self) -> List[Dict[str, Any]]:
        """Identify potential bottlenecks in operations"""
        bottlenecks = []
        
        # Check runway utilization
        if self.stats['runway_operations']:
            runway_ops = self.stats['runway_operations']
            avg_runway_time = np.mean([op['duration'] for op in runway_ops])
            
            if avg_runway_time > 4:  # More than 4 minutes average
                bottlenecks.append({
                    'type': 'runway',
                    'severity': 'high',
                    'description': 'Runway operations taking longer than expected',
                    'average_time': avg_runway_time
                })
        
        # Check gate utilization
        if self.stats['gate_utilization']:
            gate_ops = self.stats['gate_utilization']
            avg_gate_time = np.mean([op['duration'] for op in gate_ops])
            
            if avg_gate_time > 90:  # More than 90 minutes
                bottlenecks.append({
                    'type': 'gate',
                    'severity': 'medium',
                    'description': 'Gates occupied longer than optimal',
                    'average_time': avg_gate_time
                })
        
        # Check passenger boarding times
        if self.stats['passenger_boardings']:
            boarding_ops = self.stats['passenger_boardings']
            avg_boarding = np.mean([op['boarding_time'] for op in boarding_ops])
            
            if avg_boarding > 30:  # More than 30 minutes
                bottlenecks.append({
                    'type': 'boarding',
                    'severity': 'medium',
                    'description': 'Passenger boarding taking longer than expected',
                    'average_time': avg_boarding
                })
        
        return bottlenecks
    
    def _generate_recommendations(self, results: Dict) -> List[str]:
        """Generate operational recommendations based on results"""
        recommendations = []
        
        # Check flight statistics
        flight_stats = results.get('flight_statistics', {})
        avg_turnaround = flight_stats.get('average_turnaround', 0)
        
        if avg_turnaround > 120:  # More than 2 hours
            recommendations.append(
                "Consider optimizing ground operations to reduce aircraft turnaround times"
            )
        
        # Check runway utilization
        runway_stats = results.get('runway_statistics', {})
        ops_per_hour = runway_stats.get('operations_per_hour', 0)
        
        if ops_per_hour > 20:  # High utilization
            recommendations.append(
                "High runway utilization detected - consider additional runway capacity or optimized scheduling"
            )
        
        # Check gate utilization
        gate_stats = results.get('gate_statistics', {})
        gate_utilization = gate_stats.get('utilization_rate', 0)
        
        if gate_utilization > 0.8:  # 80%+ utilization
            recommendations.append(
                "High gate utilization - consider increasing gate capacity or improving gate turnover"
            )
        
        # Check bottlenecks
        bottlenecks = results.get('bottlenecks', [])
        high_severity = [b for b in bottlenecks if b.get('severity') == 'high']
        
        if high_severity:
            recommendations.append(
                "High-severity bottlenecks identified - prioritize addressing runway and critical resource constraints"
            )
        
        if not recommendations:
            recommendations.append("Operations appear to be running efficiently within normal parameters")
        
        return recommendations