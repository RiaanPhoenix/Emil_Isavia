"""
Flight Data API Integration Module

Handles fetching flight data from external aviation APIs
Supports multiple providers and data sources
"""

import requests
import json
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import os
from config.settings import API_CONFIG

logger = logging.getLogger(__name__)

class FlightDataAPI:
    """Flight data API client with multiple provider support"""
    
    def __init__(self):
        self.providers = {
            'aviationstack': self._setup_aviationstack,
            'opensky': self._setup_opensky,
            'airlabs': self._setup_airlabs
        }
        self.active_provider = None
        self.api_key = None
        self._setup_provider()
    
    def _setup_provider(self):
        """Initialize the primary API provider"""
        try:
            # Try providers in order of preference
            for provider_name in ['aviationstack', 'opensky', 'airlabs']:
                if self.providers[provider_name]():
                    self.active_provider = provider_name
                    logger.info(f"Initialized {provider_name} as flight data provider")
                    break
            
            if not self.active_provider:
                logger.warning("No flight API provider configured, using mock data")
                self.active_provider = 'mock'
        except Exception as e:
            logger.error(f"Error setting up flight API provider: {e}")
            self.active_provider = 'mock'
    
    def _setup_aviationstack(self) -> bool:
        """Setup AviationStack API"""
        api_key = os.environ.get('AVIATIONSTACK_API_KEY')
        if api_key:
            self.api_key = api_key
            self.base_url = 'http://api.aviationstack.com/v1'
            return True
        return False
    
    def _setup_opensky(self) -> bool:
        """Setup OpenSky Network API (no key required)"""
        self.base_url = 'https://opensky-network.org/api'
        return True
    
    def _setup_airlabs(self) -> bool:
        """Setup AirLabs API"""
        api_key = os.environ.get('AIRLABS_API_KEY')
        if api_key:
            self.api_key = api_key
            self.base_url = 'https://airlabs.co/api/v9'
            return True
        return False
    
    def get_flights(self, airport_code: str, hours: int = 24) -> List[Dict]:
        """
        Fetch flight data for a specific airport
        
        Args:
            airport_code: ICAO airport code (e.g., 'BIKF' for Keflavik)
            hours: Number of hours to look ahead/back
            
        Returns:
            List of flight dictionaries
        """
        try:
            if self.active_provider == 'aviationstack':
                return self._get_aviationstack_flights(airport_code, hours)
            elif self.active_provider == 'opensky':
                return self._get_opensky_flights(airport_code, hours)
            elif self.active_provider == 'airlabs':
                return self._get_airlabs_flights(airport_code, hours)
            else:
                return self._get_mock_flights(airport_code, hours)
        except Exception as e:
            logger.error(f"Error fetching flights: {e}")
            return self._get_mock_flights(airport_code, hours)
    
    def _get_aviationstack_flights(self, airport_code: str, hours: int) -> List[Dict]:
        """Fetch flights from AviationStack API"""
        params = {
            'access_key': self.api_key,
            'dep_iata': airport_code,
            'limit': 100
        }
        
        response = requests.get(f"{self.base_url}/flights", params=params, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        flights = []
        
        for flight in data.get('data', []):
            flights.append({
                'flight_number': flight.get('flight', {}).get('iata', 'N/A'),
                'airline': flight.get('airline', {}).get('name', 'Unknown'),
                'departure_airport': flight.get('departure', {}).get('airport', 'Unknown'),
                'arrival_airport': flight.get('arrival', {}).get('airport', 'Unknown'),
                'departure_time': flight.get('departure', {}).get('scheduled'),
                'arrival_time': flight.get('arrival', {}).get('scheduled'),
                'aircraft_type': flight.get('aircraft', {}).get('registration', 'Unknown'),
                'status': flight.get('flight_status', 'Unknown'),
                'passenger_capacity': self._estimate_capacity(flight.get('aircraft', {}))
            })
        
        return flights
    
    def _get_opensky_flights(self, airport_code: str, hours: int) -> List[Dict]:
        """Fetch flights from OpenSky Network API"""
        # OpenSky uses different parameters
        end_time = int(datetime.now().timestamp())
        begin_time = end_time - (hours * 3600)
        
        # Get departures
        url = f"{self.base_url}/flights/departure"
        params = {
            'airport': airport_code,
            'begin': begin_time,
            'end': end_time
        }
        
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        
        flights = []
        for flight_data in response.json():
            flights.append({
                'flight_number': flight_data.get('callsign', 'N/A').strip(),
                'departure_airport': flight_data.get('estDepartureAirport', airport_code),
                'arrival_airport': flight_data.get('estArrivalAirport', 'Unknown'),
                'departure_time': datetime.fromtimestamp(
                    flight_data.get('firstSeen', 0)
                ).isoformat() if flight_data.get('firstSeen') else None,
                'arrival_time': datetime.fromtimestamp(
                    flight_data.get('lastSeen', 0)
                ).isoformat() if flight_data.get('lastSeen') else None,
                'aircraft_type': flight_data.get('icao24', 'Unknown'),
                'status': 'Scheduled',
                'passenger_capacity': 150  # Default estimate
            })
        
        return flights
    
    def _get_airlabs_flights(self, airport_code: str, hours: int) -> List[Dict]:
        """Fetch flights from AirLabs API"""
        params = {
            'api_key': self.api_key,
            'dep_iata': airport_code
        }
        
        response = requests.get(f"{self.base_url}/schedules", params=params, timeout=10)
        response.raise_for_status()
        
        flights = []
        for flight in response.json().get('response', []):
            flights.append({
                'flight_number': flight.get('flight_iata', 'N/A'),
                'airline': flight.get('airline_name', 'Unknown'),
                'departure_airport': flight.get('dep_name', 'Unknown'),
                'arrival_airport': flight.get('arr_name', 'Unknown'),
                'departure_time': flight.get('dep_time'),
                'arrival_time': flight.get('arr_time'),
                'aircraft_type': flight.get('aircraft_icao', 'Unknown'),
                'status': flight.get('status', 'Scheduled'),
                'passenger_capacity': self._estimate_capacity_by_aircraft(
                    flight.get('aircraft_icao', '')
                )
            })
        
        return flights
    
    def _get_mock_flights(self, airport_code: str, hours: int) -> List[Dict]:
        """Generate mock flight data for testing"""
        logger.info("Using mock flight data")
        
        airlines = ['Icelandair', 'WOW Air', 'Atlantic Airways', 'SAS', 'Lufthansa']
        destinations = ['EGLL', 'KJFK', 'EDDF', 'EKCH', 'ENGM']
        aircraft_types = ['B738', 'A320', 'B763', 'DH8D']
        
        flights = []
        base_time = datetime.now()
        
        for i in range(20):  # Generate 20 mock flights
            departure_time = base_time + timedelta(hours=i * 0.5)
            arrival_time = departure_time + timedelta(hours=2 + i * 0.1)
            
            flights.append({
                'flight_number': f"FI{100 + i}",
                'airline': airlines[i % len(airlines)],
                'departure_airport': airport_code,
                'arrival_airport': destinations[i % len(destinations)],
                'departure_time': departure_time.isoformat(),
                'arrival_time': arrival_time.isoformat(),
                'aircraft_type': aircraft_types[i % len(aircraft_types)],
                'status': 'Scheduled',
                'passenger_capacity': 150 + (i * 10)
            })
        
        return flights
    
    def _estimate_capacity(self, aircraft_data: Dict) -> int:
        """Estimate passenger capacity based on aircraft data"""
        aircraft_code = aircraft_data.get('icao', '').upper()
        return self._estimate_capacity_by_aircraft(aircraft_code)
    
    def _estimate_capacity_by_aircraft(self, aircraft_code: str) -> int:
        """Estimate capacity by aircraft type"""
        capacity_map = {
            'B738': 189,  # Boeing 737-800
            'A320': 180,  # Airbus A320
            'B763': 269,  # Boeing 767-300
            'A332': 293,  # Airbus A330-200
            'DH8D': 78,   # Dash 8-400
            'B77W': 396,  # Boeing 777-300ER
        }
        
        return capacity_map.get(aircraft_code, 150)  # Default capacity
    
    def check_connection(self) -> bool:
        """Check if API connection is working"""
        try:
            if self.active_provider == 'mock':
                return True
            
            # Try a simple API call
            test_flights = self.get_flights('BIKF', 1)
            return len(test_flights) >= 0
        except Exception as e:
            logger.error(f"API connection check failed: {e}")
            return False