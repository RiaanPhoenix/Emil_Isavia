"""
Premium Parking API Integration

Connects to the real Isavia Premium Parking API to get actual
valet booking data with car locations and timing information.
"""

import requests
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import base64
import os

from app.api.flights import ValetBooking
from config import settings

log = logging.getLogger(__name__)

class PremiumParkingAPI:
    """Client for the Premium Parking API"""
    
    def __init__(self):
        self.base_url = "https://parking-api-dev-d8b2ejb0asc0gbec.northeurope-01.azurewebsites.net"
        self.username = os.getenv('PARKING_API_USERNAME', '')
        self.password = os.getenv('PARKING_API_PASSWORD', '')
        
        if not self.username or not self.password:
            log.warning("No Premium Parking API credentials found. Set PARKING_API_USERNAME and PARKING_API_PASSWORD")
    
    def get_premium_bookings(self, date_start: str, date_end: str) -> List[Dict]:
        """
        Fetch premium parking bookings for date range
        
        Args:
            date_start: Start date in YYYY-MM-DD format
            date_end: End date in YYYY-MM-DD format
            
        Returns:
            List of booking dictionaries with:
            - car_id: Parking booking key
            - arrival_datetime: Entry datetime
            - departure_datetime: Exit datetime
            - number_of_days: Days parked
            - current_car_park: Zone name (P3/Gull/Return)
            - current_car_park_id: Numeric zone ID
        """
        if not self.username or not self.password:
            log.warning("Cannot fetch from Premium Parking API - no credentials")
            return []
        
        try:
            # Prepare authentication
            credentials = base64.b64encode(f"{self.username}:{self.password}".encode()).decode()
            headers = {
                'Authorization': f'Basic {credentials}',
                'Accept': 'application/json'
            }
            
            # API parameters
            params = {
                'date_start': date_start,
                'date_end': date_end
            }
            
            log.info(f"Fetching premium bookings from {date_start} to {date_end}")
            
            response = requests.get(
                f"{self.base_url}/premium-bookings",
                headers=headers,
                params=params,
                timeout=30
            )
            
            response.raise_for_status()
            bookings = response.json()
            
            log.info(f"Retrieved {len(bookings)} premium bookings from API")
            return bookings
            
        except requests.exceptions.RequestException as e:
            log.error(f"Error fetching premium bookings: {e}")
            return []
        except Exception as e:
            log.error(f"Unexpected error in premium bookings API: {e}")
            return []
    
    def bookings_to_valet_bookings(self, api_bookings: List[Dict]) -> List[ValetBooking]:
        """
        Convert Premium Parking API bookings to our ValetBooking format
        
        Args:
            api_bookings: Raw bookings from the Premium Parking API
            
        Returns:
            List of ValetBooking objects suitable for optimization
        """
        valet_bookings = []
        
        for i, booking in enumerate(api_bookings):
            try:
                # Parse datetimes
                arrival_dt = self._parse_datetime(booking.get('arrival_datetime'))
                departure_dt = self._parse_datetime(booking.get('departure_datetime'))
                
                if not arrival_dt or not departure_dt:
                    log.warning(f"Invalid datetime in booking {booking.get('car_id', 'unknown')}")
                    continue
                
                # Create ValetBooking
                # In our valet model:
                # - departure_time = when customer drops off car (arrival to airport)
                # - arrival_time = when customer returns (departure from airport)
                valet_booking = ValetBooking(
                    booking_id=f"PV-{booking.get('car_id', f'REAL-{i+1:04d}')}",
                    flight_out=f"REAL-OUT-{i+1}",  # We don't have flight numbers from parking API
                    flight_in=f"REAL-IN-{i+1}",
                    departure_time=arrival_dt,      # Customer arrives = drops off car
                    arrival_time=departure_dt,      # Customer departs = picks up car
                    car_plate=str(booking.get('car_id', f'REAL-{i+1}')),
                    # Additional metadata
                    pax_name=f"Premium Customer {i+1}",
                    current_zone=self._normalize_zone(booking.get('current_car_park', '')),
                    days_parked=booking.get('number_of_days', 1)
                )
                
                valet_bookings.append(valet_booking)
                
            except Exception as e:
                log.error(f"Error processing booking {i}: {e}")
                continue
        
        log.info(f"Converted {len(valet_bookings)} API bookings to valet bookings")
        return valet_bookings
    
    def _parse_datetime(self, dt_string: Optional[str]) -> Optional[datetime]:
        """Parse datetime string from API"""
        if not dt_string:
            return None
        
        try:
            # Handle various datetime formats
            # Try ISO format first
            if 'T' in dt_string:
                return datetime.fromisoformat(dt_string.replace('Z', '+00:00')).replace(tzinfo=None)
            else:
                # Try date only
                return datetime.strptime(dt_string, '%Y-%m-%d')
        except Exception as e:
            log.error(f"Error parsing datetime '{dt_string}': {e}")
            return None
    
    def _normalize_zone(self, zone_name: str) -> str:
        """Normalize zone names from API to our internal names"""
        zone_mapping = {
            'P3': 'p3',
            'Gull': 'gull', 
            'Return': 'delivery',
            'Reception': 'reception'
        }
        
        return zone_mapping.get(zone_name, 'unknown')


def get_real_valet_bookings(
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None
) -> List[ValetBooking]:
    """
    Fetch real Premium valet bookings from the API
    
    Args:
        start_date: Start date for bookings (defaults to today)
        end_date: End date for bookings (defaults to start_date + planning horizon)
        
    Returns:
        List of ValetBooking objects with real data
    """
    if not start_date:
        start_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    
    if not end_date:
        end_date = start_date + timedelta(hours=settings.PLANNING_HORIZON_H)
    
    # Format dates for API
    date_start = start_date.strftime('%Y-%m-%d')
    date_end = end_date.strftime('%Y-%m-%d')
    
    # Fetch from API
    api_client = PremiumParkingAPI()
    api_bookings = api_client.get_premium_bookings(date_start, date_end)
    
    if not api_bookings:
        log.info("No bookings from Premium Parking API, using mock data")
        # Fall back to existing mock generation
        from app.api.flights import generate_bookings_from_api
        return generate_bookings_from_api(start_date, 60)
    
    # Convert to valet bookings
    valet_bookings = api_client.bookings_to_valet_bookings(api_bookings)
    
    # Sort by arrival time
    valet_bookings.sort(key=lambda b: b.departure_time)
    
    return valet_bookings


def test_api_connection() -> Dict[str, any]:
    """Test connection to the Premium Parking API"""
    api_client = PremiumParkingAPI()
    
    if not api_client.username or not api_client.password:
        return {
            'status': 'error',
            'message': 'No API credentials configured',
            'connected': False
        }
    
    try:
        # Test with today's date
        today = datetime.now().strftime('%Y-%m-%d')
        bookings = api_client.get_premium_bookings(today, today)
        
        return {
            'status': 'success',
            'message': f'Successfully connected - found {len(bookings)} bookings',
            'connected': True,
            'bookings_count': len(bookings)
        }
    except Exception as e:
        return {
            'status': 'error',
            'message': f'API connection failed: {e}',
            'connected': False
        }