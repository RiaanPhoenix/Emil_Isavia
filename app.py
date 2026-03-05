#!/usr/bin/env python3
"""
Emil Isavia - Aviation Traffic Optimization System
Main Flask Application

This application integrates external flight API data with:
- GurobiPy optimization models for flight scheduling and pricing
- SimPy simulation models for airport operations
"""

from flask import Flask, render_template, request, jsonify, redirect, url_for
import json
import logging
from datetime import datetime, timedelta
import os
from src.api.flight_data import FlightDataAPI
from src.optimization.flight_optimizer import FlightOptimizer
from src.simulation.airport_simulator import AirportSimulator

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-key-change-in-production')

# Initialize components
flight_api = FlightDataAPI()
optimizer = FlightOptimizer()
simulator = AirportSimulator()

@app.route('/')
def index():
    """Main dashboard showing system overview"""
    return render_template('index.html')

@app.route('/api/flights')
def get_flights():
    """API endpoint to fetch flight data"""
    try:
        # Get query parameters
        airport_code = request.args.get('airport', 'BIKF')  # Keflavik Airport default
        hours = int(request.args.get('hours', 24))
        
        # Fetch flight data
        flights = flight_api.get_flights(airport_code, hours)
        
        return jsonify({
            'success': True,
            'data': flights,
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        logger.error(f"Error fetching flight data: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/optimize', methods=['GET', 'POST'])
def optimize_flights():
    """Flight scheduling and pricing optimization"""
    if request.method == 'POST':
        try:
            data = request.get_json()
            
            # Extract parameters
            flights = data.get('flights', [])
            capacity_constraints = data.get('capacity_constraints', {})
            pricing_tiers = data.get('pricing_tiers', {})
            
            # Run optimization
            result = optimizer.optimize_schedule(
                flights=flights,
                capacity_constraints=capacity_constraints,
                pricing_tiers=pricing_tiers
            )
            
            return jsonify({
                'success': True,
                'optimization_result': result,
                'timestamp': datetime.now().isoformat()
            })
            
        except Exception as e:
            logger.error(f"Optimization error: {e}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500
    
    return render_template('optimize.html')

@app.route('/simulate', methods=['GET', 'POST'])
def simulate_airport():
    """Airport operations simulation"""
    if request.method == 'POST':
        try:
            data = request.get_json()
            
            # Extract simulation parameters
            flights = data.get('flights', [])
            airport_config = data.get('airport_config', {})
            simulation_duration = data.get('duration', 24)  # hours
            
            # Run simulation
            result = simulator.run_simulation(
                flights=flights,
                airport_config=airport_config,
                duration=simulation_duration
            )
            
            return jsonify({
                'success': True,
                'simulation_result': result,
                'timestamp': datetime.now().isoformat()
            })
            
        except Exception as e:
            logger.error(f"Simulation error: {e}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500
    
    return render_template('simulate.html')

@app.route('/dashboard')
def dashboard():
    """Integrated dashboard showing optimization and simulation results"""
    return render_template('dashboard.html')

@app.route('/api/status')
def system_status():
    """System health check"""
    status = {
        'api_connection': flight_api.check_connection(),
        'optimizer_ready': optimizer.is_ready(),
        'simulator_ready': simulator.is_ready(),
        'timestamp': datetime.now().isoformat()
    }
    
    return jsonify(status)

@app.errorhandler(404)
def not_found(error):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_error(error):
    return render_template('500.html'), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('DEBUG', 'False').lower() == 'true'
    
    logger.info(f"Starting Emil Isavia application on port {port}")
    app.run(host='0.0.0.0', port=port, debug=debug)