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
from dotenv import load_dotenv

load_dotenv()
from flask import Flask, render_template, request, jsonify, session, redirect, url_for

from app.api.flights import generate_bookings_from_api
from app.api.parking_api import get_real_valet_bookings, test_api_connection
from app.optimization.valet_optimizer import ValetOptimizer
from app.optimization.greedy_scheduler import schedule_day, schedule_range
from app.simulation.valet_sim import run_monte_carlo_simulation, ValetSimulation, generate_fifo_plan
from app.simulation.valet_sim_v2 import SimParams, run_scenario as run_scenario_v2
from config import settings
import numpy as np

# ── Application setup ───────────────────────────────────────────────

app = Flask(__name__, 
            template_folder='app/templates',
            static_folder='app/static')
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
    """Get current valet bookings from parking API or flight API."""
    try:
        # Get parameters
        date_str = request.args.get('date')
        n_customers = int(request.args.get('customers', 60))
        use_real_api = request.args.get('use_real', 'true').lower() == 'true'
        
        if date_str:
            base_date = datetime.fromisoformat(date_str)
        else:
            base_date = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        
        # Choose data source
        if use_real_api:
            # Try real Premium Parking API first
            end_date = base_date + timedelta(hours=settings.PLANNING_HORIZON_H)
            bookings = get_real_valet_bookings(base_date, end_date)
            data_source = "premium_parking_api"
        else:
            # Use flight-based mock data
            bookings = generate_bookings_from_api(base_date, n_customers)
            data_source = "flight_api_mock"
        
        return jsonify({
            "success": True,
            "data": [booking.to_dict() for booking in bookings],
            "base_date": base_date.isoformat(),
            "count": len(bookings),
            "data_source": data_source,
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
        
        # Test API connections
        api_status = "ready"
        parking_api_status = "not_configured"
        
        try:
            # Test Premium Parking API
            parking_test = test_api_connection()
            if parking_test['connected']:
                parking_api_status = "connected"
                api_status = "premium_api_available"
            else:
                parking_api_status = "error"
                
            # Fallback to flight API test
            if parking_api_status != "connected":
                bookings = generate_bookings_from_api(n_premium_customers=1)
                if bookings:
                    api_status = "mock_data_fallback"
                else:
                    api_status = "error"
        except Exception as e:
            api_status = "error"
            parking_api_status = "error"
        
        return jsonify({
            "status": "healthy",
            "components": {
                "optimization": opt_status,
                "simulation": sim_status,
                "flight_api": api_status,
                "premium_parking_api": parking_api_status,
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


@app.route('/api/greedy-schedule', methods=['POST'])
def api_greedy_schedule():
    """Run the greedy day-plan scheduler for a given date."""
    try:
        data = request.get_json(force=True) or {}
        day_str       = data.get('date', datetime.now().strftime('%Y-%m-%d'))
        day_movers    = int(data.get('day_movers',    2))
        night_workers = int(data.get('night_workers', 2))
        supervisor    = bool(data.get('supervisor',   True))
        move2_window  = int(data.get('move2_window',  60))
        # Basic validation
        datetime.strptime(day_str, '%Y-%m-%d')
        result = schedule_day(
            day_str,
            day_movers=day_movers,
            night_workers=night_workers,
            supervisor=supervisor,
            move2_window=move2_window,
        )
        return jsonify(result)
    except ValueError as e:
        return jsonify({'error': f'Invalid date format: {e}'}), 400
    except Exception as e:
        log.exception('Greedy schedule error')
        return jsonify({'error': str(e)}), 500


@app.route('/api/greedy-schedule-range', methods=['POST'])
def api_greedy_schedule_range():
    """Run the greedy scheduler for a date range."""
    try:
        data          = request.get_json(force=True) or {}
        date_from     = data.get('date_from', datetime.now().strftime('%Y-%m-%d'))
        date_to       = data.get('date_to',   date_from)
        day_movers    = int(data.get('day_movers',    2))
        night_workers = int(data.get('night_workers', 2))
        supervisor    = bool(data.get('supervisor',   True))
        move2_window  = int(data.get('move2_window',  60))
        datetime.strptime(date_from, '%Y-%m-%d')
        datetime.strptime(date_to,   '%Y-%m-%d')
        result = schedule_range(date_from, date_to, day_movers, night_workers, supervisor, move2_window)
        return jsonify(result)
    except ValueError as e:
        return jsonify({'error': f'Invalid date format: {e}'}), 400
    except Exception as e:
        log.exception('Greedy schedule range error')
        return jsonify({'error': str(e)}), 500


@app.route('/live-feed')
def live_feed_page():
    """Live parking occupancy feed page."""
    return render_template('live_feed.html')


@app.route('/api/live-status')
def api_live_status():
    """Get real-time parking occupancy data."""
    try:
        now = datetime.utcnow()
        # Fetch bookings for a window around now
        start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end_date = start_date + timedelta(days=1)
        
        # Try to get real bookings, fallback to mock if needed
        try:
            bookings = get_real_valet_bookings(start_date, end_date)
            data_source = "premium_parking_api"
        except Exception:
            # Use flight-based mock data as fallback
            bookings = generate_bookings_from_api(start_date, 30)
            data_source = "flight_api_mock"
        
        # Calculate occupancy based on booking timeline
        occupancy = {
            "reception": 0,
            "gull": 0, 
            "p3": 0,
            "delivery": 0
        }
        
        active_bookings = []
        
        for b in bookings:
            # Determine current status/zone based on timing
            # More sophisticated zone assignment based on valet workflow:
            # 1. Car arrives -> Reception (brief)
            # 2. Car moved to storage -> Gull or P3 (bulk of time)
            # 3. Car prepared for return -> Delivery (15 min before pickup)
            
            minutes_until_departure = (b.departure_time - now).total_seconds() / 60
            minutes_since_arrival = (now - b.arrival_time).total_seconds() / 60
            
            current_zone = None
            
            if now >= b.arrival_time and now <= b.departure_time:
                # Car is currently parked
                if minutes_until_departure <= 15:
                    # Car should be in delivery area (15 min rule)
                    current_zone = "delivery"
                elif minutes_since_arrival <= 30:
                    # Recently arrived, might still be in reception
                    current_zone = "reception"
                else:
                    # In storage - assign to Gull or P3 based on duration
                    hours_duration = (b.departure_time - b.arrival_time).total_seconds() / 3600
                    if hours_duration <= 24:
                        current_zone = "gull"  # Short-term
                    else:
                        current_zone = "p3"    # Long-term
                
                if current_zone and current_zone in occupancy:
                    occupancy[current_zone] += 1
                    active_bookings.append({
                        "id": b.booking_id,
                        "plate": getattr(b, 'car_plate', f"***{b.booking_id[-3:]}"),
                        "zone": current_zone,
                        "since": b.arrival_time.isoformat(),
                        "flight": getattr(b, 'flight_out', 'N/A'),
                        "departure_in_min": max(0, int(minutes_until_departure))
                    })
        
        # Add some randomization for demo purposes if using mock data
        if data_source == "flight_api_mock":
            import random
            random.seed(int(now.timestamp()) // 30)  # Change every 30 seconds
            
            # Add some baseline occupancy
            occupancy["reception"] += random.randint(0, 3)
            occupancy["gull"] += random.randint(5, 15) 
            occupancy["p3"] += random.randint(20, 40)
            occupancy["delivery"] += random.randint(0, 5)
            
            # Don't exceed capacities
            occupancy["reception"] = min(occupancy["reception"], settings.CAPACITY_RECEPTION)
            occupancy["gull"] = min(occupancy["gull"], settings.CAPACITY_GULL)
            occupancy["p3"] = min(occupancy["p3"], settings.CAPACITY_P3)
            occupancy["delivery"] = min(occupancy["delivery"], settings.CAPACITY_DELIVERY)
        
        # Arriving soon: cars expected within the next 2 hours
        arriving_soon = []
        for b in bookings:
            minutes_until_arrival = (b.departure_time - now).total_seconds() / 60
            if 0 < minutes_until_arrival <= 120:
                arriving_soon.append({
                    "id": b.booking_id,
                    "plate": getattr(b, 'car_plate', f"***{b.booking_id[-3:]}"),
                    "arrives_in_min": int(minutes_until_arrival),
                    "flight": getattr(b, 'flight_out', 'N/A'),
                })
        arriving_soon.sort(key=lambda x: x["arrives_in_min"])

        return jsonify({
            "success": True,
            "timestamp": now.isoformat(),
            "data_source": data_source,
            "occupancy": occupancy,
            "capacities": {
                "reception": settings.CAPACITY_RECEPTION,
                "gull": settings.CAPACITY_GULL,
                "p3": settings.CAPACITY_P3,
                "delivery": settings.CAPACITY_DELIVERY
            },
            "available": {
                "reception": settings.CAPACITY_RECEPTION - occupancy["reception"],
                "gull": settings.CAPACITY_GULL - occupancy["gull"],
                "p3": settings.CAPACITY_P3 - occupancy["p3"],
                "delivery": settings.CAPACITY_DELIVERY - occupancy["delivery"]
            },
            "active_bookings": active_bookings,
            "arriving_soon": arriving_soon
        })
        
    except Exception as e:
        log.error("Live status error: %s", e)
        return jsonify({
            "success": False, 
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }), 500


@app.route('/api/simulate-combined', methods=['POST'])
def api_simulate_combined():
    """Run optimized + baseline simulation together for comparison."""
    try:
        data = request.get_json()

        base_time_str = data.get('base_time')
        if base_time_str:
            base_time = datetime.fromisoformat(base_time_str)
        else:
            base_time = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

        n_runs         = int(data.get('n_runs', settings.SIM_RUNS))
        duration_hours = float(data.get('duration_hours', 24))
        delay_std      = float(data.get('delay_std', settings.SIM_FLIGHT_DELAY_STD))
        drive_std      = float(data.get('drive_std', settings.SIM_DRIVE_TIME_STD))
        n_customers    = int(data.get('n_customers', 60))
        staff_count    = int(data.get('staff_count', settings.MAX_STAFF))
        lead_time      = float(data.get('lead_time', settings.DELIVERY_LEAD_TIME))

        # ── Generate bookings ──────────────────────────────────────────
        bookings_data = data.get('bookings', [])
        from app.api.flights import ValetBooking
        if bookings_data:
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
            bookings = generate_bookings_from_api(base_time, n_customers)

        # ── Build a minimal plan for the simulation ────────────────────
        # Run optimizer with the specified staff count
        opt_settings_override = {
            'delay_std': delay_std,
            'drive_std': drive_std,
            'staff_count': staff_count,
            'lead_time': lead_time,
        }

        try:
            result = optimizer.optimize(bookings, base_time)
        except Exception:
            from app.optimization.valet_optimizer import OptimizationResult
            result = OptimizationResult(
                status='heuristic',
                total_staff_hours=0,
                staff_schedule=[],
                car_movements=[],
                zone_occupancy={},
                solve_time_seconds=0,
                solver_used='none',
            )

        # ── Override simulation noise params on settings (thread-local safe enough for demo) ──
        orig_delay = settings.SIM_FLIGHT_DELAY_STD
        orig_drive = settings.SIM_DRIVE_TIME_STD
        orig_staff = settings.MAX_STAFF
        settings.SIM_FLIGHT_DELAY_STD = delay_std
        settings.SIM_DRIVE_TIME_STD   = drive_std
        settings.MAX_STAFF            = staff_count

        try:
            # ── Optimized simulation ───────────────────────────────────
            opt_result = run_monte_carlo_simulation(
                bookings, result, base_time, n_runs, duration_hours
            )

            # ── Baseline simulation (FIFO — naive scheduling, no optimisation) ──
            baseline_plan = generate_fifo_plan(bookings, base_time, lead_time_min=lead_time, duration_hours=duration_hours)
            base_result = run_monte_carlo_simulation(
                bookings, baseline_plan, base_time, n_runs, duration_hours
            )
        finally:
            settings.SIM_FLIGHT_DELAY_STD = orig_delay
            settings.SIM_DRIVE_TIME_STD   = orig_drive
            settings.MAX_STAFF            = orig_staff

        # ── Build per-run chart data ───────────────────────────────────
        opt_sls  = [r['service_level'] for r in opt_result.get('results', [])]
        base_sls = [r['service_level'] for r in base_result.get('results', [])]

        # Avg earliness = negative of avg_wait_time (car ready before customer)
        def avg_earliness(res):
            wt = res.get('summary', {}).get('avg_wait_time', {}).get('mean', 0)
            return max(0, -wt)

        # Zone peak occupancy (average across runs)
        def avg_zone_peak(res):
            peaks = {}
            for r in res.get('results', []):
                for zone, val in r.get('zone_max_occupancy', {}).items():
                    peaks.setdefault(zone, []).append(val)
            return {z: float(np.mean(v)) for z, v in peaks.items()}

        return jsonify({
            'success': True,
            'n_runs': n_runs,
            'bookings_count': len(bookings),
            'params': {
                'staff_count': staff_count,
                'duration_hours': duration_hours,
                'delay_std': delay_std,
                'drive_std': drive_std,
                'n_customers': n_customers,
                'lead_time': lead_time,
            },
            'optimized': {
                'summary': opt_result.get('summary', {}),
                'service_levels': opt_sls,
                'avg_earliness_min': avg_earliness(opt_result),
                'zone_peak': avg_zone_peak(opt_result),
                'recommendations': opt_result.get('recommendations', []),
            },
            'baseline': {
                'summary': base_result.get('summary', {}),
                'service_levels': base_sls,
                'avg_earliness_min': avg_earliness(base_result),
                'zone_peak': avg_zone_peak(base_result),
            },
            'timestamp': datetime.utcnow().isoformat(),
        })

    except Exception as e:
        log.error('simulate-combined error: %s', e, exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/scenario', methods=['POST'])
def api_scenario():
    """Run one or two named scenarios using the v2 simulation engine."""
    try:
        data = request.get_json()

        def _build_params(d):
            return SimParams(
                date_start             = d.get('date_start',             '2025-06-01'),
                date_end               = d.get('date_end',               '2025-06-30'),
                n_runs                 = int(d.get('n_runs',             10)),
                staff_day              = int(d.get('staff_day',          3)),
                staff_night            = int(d.get('staff_night',        2)),
                has_supervisor         = bool(d.get('has_supervisor',    True)),
                retrieval_lead         = int(d.get('retrieval_lead',     90)),
                stochastic             = bool(d.get('stochastic',        True)),
                flight_delay_std       = float(d.get('flight_delay_std', 15.0)),
                drive_time_variability = float(d.get('drive_time_variability', 0.15)),
                demand_scale           = float(d.get('demand_scale',     1.0)),
            )

        scenario_a = _build_params(data.get('scenario_a', data))
        result_a   = run_scenario_v2(scenario_a)

        result_b = None
        if data.get('scenario_b'):
            scenario_b = _build_params(data['scenario_b'])
            result_b   = run_scenario_v2(scenario_b)

        return jsonify({
            'success':    True,
            'scenario_a': result_a,
            'scenario_b': result_b,
            'timestamp':  datetime.utcnow().isoformat(),
        })

    except Exception as e:
        log.error('scenario error: %s', e, exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/test-parking-api')
def api_test_parking():
    """Test Premium Parking API connection."""
    try:
        result = test_api_connection()
        return jsonify(result)
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': f'Test failed: {e}',
            'connected': False
        }), 500


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