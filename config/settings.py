"""
Configuration settings for Emil Isavia application
"""

import os
from datetime import timedelta

# API Configuration
API_CONFIG = {
    'aviation_stack': {
        'base_url': 'http://api.aviationstack.com/v1',
        'api_key_env': 'AVIATIONSTACK_API_KEY',
        'timeout': 10,
        'rate_limit': 1000  # requests per month for free tier
    },
    'opensky': {
        'base_url': 'https://opensky-network.org/api',
        'timeout': 10,
        'rate_limit': None  # No official limit
    },
    'airlabs': {
        'base_url': 'https://airlabs.co/api/v9',
        'api_key_env': 'AIRLABS_API_KEY',
        'timeout': 10,
        'rate_limit': 1000  # requests per month for free tier
    }
}

# Airport Configuration
AIRPORT_CONFIG = {
    'default_airport': 'BIKF',  # Keflavik International Airport
    'timezone': 'Atlantic/Reykjavik',
    
    # Default capacity constraints
    'capacity': {
        'runways': 2,
        'gates': 12,
        'total_slots': 48,  # 30-minute slots in 24 hours
        'runway_capacity': 4,  # Operations per slot
        'premium_slots': 20,
        'checkin_counters': 8,
        'security_lanes': 4,
        'baggage_belts': 6,
        'ground_crew_teams': 10,
        'fuel_trucks': 4,
        'catering_trucks': 3
    }
}

# Optimization Configuration
OPTIMIZATION_CONFIG = {
    'gurobi': {
        'time_limit': 300,  # 5 minutes
        'gap': 0.01,  # 1% optimality gap
        'log_to_console': False
    },
    
    'pricing': {
        'base_price_domestic': 150.0,
        'base_price_international': 300.0,
        'premium_multiplier': 1.5,
        'demand_elasticity': 0.8
    },
    
    'scheduling': {
        'min_turnaround_time': 60,  # minutes
        'preferred_slot_spacing': 15,  # minutes
        'peak_hours': [(6, 10), (16, 20)],  # Peak traffic hours
        'night_curfew': (23, 6)  # Night operations restrictions
    }
}

# Simulation Configuration
SIMULATION_CONFIG = {
    'default_duration': 24.0,  # hours
    'random_seed': None,  # Set for reproducible results
    
    'passenger_flow': {
        'checkin_window': 120,  # minutes before departure
        'security_time_per_passenger': (1, 4),  # min, max minutes
        'boarding_rate': 0.5,  # minutes per passenger
        'load_factor_range': (0.6, 0.95)
    },
    
    'ground_operations': {
        'baggage_time': (15, 30),  # min, max minutes
        'fuel_time': (20, 40),
        'catering_time': (10, 25),
        'cleaning_time': (15, 35),
        'gate_time': (30, 90)
    }
}

# Web Application Configuration
WEB_CONFIG = {
    'host': '0.0.0.0',
    'port': 5000,
    'debug': False,
    'secret_key': os.environ.get('SECRET_KEY', 'dev-key-change-in-production'),
    
    # Session configuration
    'permanent_session_lifetime': timedelta(days=1),
    
    # Cache configuration
    'cache_timeout': 300,  # 5 minutes
    
    # Static files
    'send_file_max_age': 3600  # 1 hour
}

# Logging Configuration
LOGGING_CONFIG = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'standard': {
            'format': '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
        },
    },
    'handlers': {
        'default': {
            'level': 'INFO',
            'formatter': 'standard',
            'class': 'logging.StreamHandler',
        },
        'file': {
            'level': 'INFO',
            'formatter': 'standard',
            'class': 'logging.FileHandler',
            'filename': 'logs/emil_isavia.log',
            'mode': 'a',
        },
    },
    'loggers': {
        '': {
            'handlers': ['default', 'file'],
            'level': 'INFO',
            'propagate': False
        }
    }
}

# Database Configuration (if needed for future expansion)
DATABASE_CONFIG = {
    'sqlite': {
        'path': 'data/emil_isavia.db'
    },
    'postgres': {
        'host': os.environ.get('DB_HOST', 'localhost'),
        'port': int(os.environ.get('DB_PORT', 5432)),
        'database': os.environ.get('DB_NAME', 'emil_isavia'),
        'username': os.environ.get('DB_USER', 'postgres'),
        'password': os.environ.get('DB_PASSWORD', '')
    }
}

# Environment-specific settings
ENVIRONMENT = os.environ.get('ENVIRONMENT', 'development')

if ENVIRONMENT == 'production':
    WEB_CONFIG['debug'] = False
    LOGGING_CONFIG['loggers']['']['level'] = 'WARNING'
elif ENVIRONMENT == 'development':
    WEB_CONFIG['debug'] = True
    LOGGING_CONFIG['loggers']['']['level'] = 'DEBUG'

# Export commonly used configurations
DEFAULT_AIRPORT = AIRPORT_CONFIG['default_airport']
DEFAULT_CAPACITY = AIRPORT_CONFIG['capacity']
DEFAULT_OPTIMIZATION = OPTIMIZATION_CONFIG
DEFAULT_SIMULATION = SIMULATION_CONFIG