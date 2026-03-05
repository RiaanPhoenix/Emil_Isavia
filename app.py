"""
Emil Isavia — Premium Valet Parking Optimization & Simulation Web App

Main Flask application that integrates:
1. External flight API data (customer arrival/departure times)
2. GurobiPy optimization (staff scheduling, car movements)  
3. SimPy simulation (stress-testing under uncertainty)

The system solves Isavia's valet parking operation at Keflavík Airport.
"""

import logging
import json
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify, session, redirect, url_for

from app.api.flights import generate_bookings_from_api
from app.optimization.valet_optimizer import ValetOptimizer
from app.simulation.valet_sim import run_monte_carlo_simulation
from config import settings

# ── Application setup ───────────────────────────────────────────────

app = Flask(__name__)
app.secret_key = settings.SECRET_KEY

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
log = logging.getLogger(__name__)

# Initialize components
optimizer = ValetOptimizer()


# ── Routes ──────────────────────────────────────────────────────────

@app.route('/')
def index():
    """Main dashboard."""
    return render_template('index.html')


@app.route('/api/bookings')
def api_bookings():
    """Get current valet bookings from flight API."""
    try:
        # Get parameters
        date_str = request.args.get('date')
        n_customers = int(request.args.get('customers', 60))
        
        if date_str:
            base_date = datetime.fromisoformat(date_str)
        else:
            base_date = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        
        # Generate bookings
        bookings = generate_bookings_from_api(base_date, n_customers)
        
        return jsonify({
            "success": True,
            "data": [booking.to_dict() for booking in bookings],
            "base_date": base_date.isoformat(),
            "count": len(bookings),
            "timestamp": datetime.utcnow().isoformat()
        })
        
    except Exception as e:
        log.error("Error generating bookings: %s", e)
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route('/api/optimize', methods=['POST'])
def api_optimize():
    """Run valet parking optimization."""
    try:
        data = request.get_json()
        
        # Parse request
        base_time_str = data.get('base_time')
        if base_time_str:
            base_time = datetime.fromisoformat(base_time_str)
        else:
            base_time = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        
        # Get or generate bookings
        bookings_data = data.get('bookings')
        if bookings_data:
            # Use provided bookings
            from app.api.flights import ValetBooking
            bookings = []
            for b in bookings_data:
                booking = ValetBooking(
                    booking_id=b['booking_id'],
                    flight_out=b['flight_out'],
                    flight_in=b['flight_in'],
                    departure_time=datetime.fromisoformat(b['departure_time']),
                    arrival_time=datetime.fromisoformat(b['arrival_time']),
                    car_plate=b.get('car_plate', ''),
                )
                bookings.append(booking)
        else:
            # Generate new bookings
            n_customers = data.get('n_customers', 60)
            bookings = generate_bookings_from_api(base_time, n_customers)
        
        # Run optimization
        log.info("Running optimization for %d bookings", len(bookings))
        result = optimizer.optimize(bookings, base_time)
        
        return jsonify({
            "success": True,
            "optimization_result": result.to_dict(),
            "bookings_count": len(bookings),
            "base_time": base_time.isoformat(),
            "timestamp": datetime.utcnow().isoformat()
        })
        
    except Exception as e:
        log.error("Optimization error: %s", e)
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route('/api/simulate', methods=['POST'])
def api_simulate():
    """Run valet parking simulation."""
    try:
        data = request.get_json()
        
        # Parse request
        base_time_str = data.get('base_time')
        if base_time_str:
            base_time = datetime.fromisoformat(base_time_str)
        else:
            base_time = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        
        # Get bookings and optimization plan
        bookings_data = data.get('bookings', [])
        plan_data = data.get('optimization_plan')
        
        if not bookings_data:
            return jsonify({
                "success": False,
                "error": "No bookings provided for simulation"
            }), 400
        
        if not plan_data:
            return jsonify({
                "success": False,
                "error": "No optimization plan provided for simulation"
            }), 400
        
        # Parse bookings
        from app.api.flights import ValetBooking
        bookings = []
        for b in bookings_data:
            booking = ValetBooking(
                booking_id=b['booking_id'],
                flight_out=b['flight_out'], 
                flight_in=b['flight_in'],
                departure_time=datetime.fromisoformat(b['departure_time']),
                arrival_time=datetime.fromisoformat(b['arrival_time']),
                car_plate=b.get('car_plate', ''),
            )
            bookings.append(booking)
        
        # Parse optimization plan
        from app.optimization.valet_optimizer import OptimizationResult
        plan = OptimizationResult(
            status=plan_data['status'],
            total_staff_hours=plan_data['total_staff_hours'],
            staff_schedule=plan_data['staff_schedule'],
            car_movements=plan_data['car_movements'],
            zone_occupancy=plan_data['zone_occupancy'],
            solve_time_seconds=plan_data.get('solve_time_seconds', 0),
            solver_used=plan_data.get('solver_used', 'unknown')
        )
        
        # Run simulation
        n_runs = data.get('n_runs', settings.SIM_RUNS)
        duration_hours = data.get('duration_hours', 24)
        
        log.info("Running %d simulation runs for %d bookings", n_runs, len(bookings))
        result = run_monte_carlo_simulation(bookings, plan, base_time, n_runs, duration_hours)
        
        return jsonify({
            "success": True,
            "simulation_result": result,
            "bookings_count": len(bookings),
            "base_time": base_time.isoformat(),
            "timestamp": datetime.utcnow().isoformat()
        })
        
    except Exception as e:
        log.error("Simulation error: %s", e)
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route('/api/status')
def api_status():
    """System health check."""
    try:
        # Test optimization
        opt_status = "ready"
        try:
            from app.optimization.valet_optimizer import GUROBI_AVAILABLE
            if GUROBI_AVAILABLE:
                opt_status = "gurobi_available"
            else:
                opt_status = "heuristic_only"
        except Exception:
            opt_status = "error"
        
        # Test simulation
        sim_status = "ready"
        try:
            import simpy
            sim_status = "simpy_available"
        except ImportError:
            sim_status = "error"
        
        # Test API connection
        api_status = "ready"
        try:
            # Quick test of flight API
            bookings = generate_bookings_from_api(n_premium_customers=1)
            if bookings:
                api_status = "connected"
            else:
                api_status = "mock_data"
        except Exception:
            api_status = "error"
        
        return jsonify({
            "status": "healthy",
            "components": {
                "optimization": opt_status,
                "simulation": sim_status,
                "flight_api": api_status,
            },
            "config": {
                "airport": settings.AIRPORT_ICAO,
                "max_staff": settings.MAX_STAFF,
                "planning_horizon_h": settings.PLANNING_HORIZON_H,
                "capacities": {
                    "reception": settings.CAPACITY_RECEPTION,
                    "gull": settings.CAPACITY_GULL,
                    "p3": settings.CAPACITY_P3,
                    "delivery": settings.CAPACITY_DELIVERY,
                }
            },
            "timestamp": datetime.utcnow().isoformat()
        })
        
    except Exception as e:
        return jsonify({
            "status": "error",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }), 500


@app.route('/optimize')
def optimize_page():
    """Optimization interface page."""
    return render_template('optimize.html')


@app.route('/simulate') 
def simulate_page():
    """Simulation interface page."""
    return render_template('simulate.html')


@app.route('/dashboard')
def dashboard_page():
    """Analytics dashboard page."""
    return render_template('dashboard.html')


# ── Error handlers ──────────────────────────────────────────────────

@app.errorhandler(404)
def not_found(error):
    return render_template('404.html'), 404


@app.errorhandler(500)
def internal_error(error):
    return render_template('500.html'), 500


# ── Main ────────────────────────────────────────────────────────────

if __name__ == '__main__':
    log.info("Starting Emil Isavia valet parking optimization system")
    log.info("Airport: %s, Max staff: %d, Planning horizon: %dh", 
             settings.AIRPORT_ICAO, settings.MAX_STAFF, settings.PLANNING_HORIZON_H)
    
    app.run(
        host='0.0.0.0',
        port=settings.PORT,
        debug=settings.DEBUG
    )