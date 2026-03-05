# Emil Isavia — Premium Valet Parking Optimization & Simulation

A comprehensive web application that optimizes Isavia's Premium valet parking operations at Keflavík International Airport. The system integrates **real flight data** from external APIs, **GurobiPy optimization** for staff scheduling and car movements, and **SimPy simulation** for stress-testing under stochastic conditions.

## 🚗 The Problem

Isavia operates a Premium valet parking service at Keflavík Airport where:
- Customers drop their cars at **Reception** (14 spots) before departure
- Staff move cars to storage areas: **Gull** (50 spots, close) or **P3** (150 spots, far)
- Cars must be ready at **Delivery** (20 spots) ≥15 minutes before customer returns
- **Hard constraint**: Cars MUST be ready on time
- **Objective**: Minimize total staff time while meeting service levels

### Physical Layout
```
Reception (14) ──3min──► Gull (50) ──4min──► Delivery (20)
     │                                          ▲
     └────8min──► P3 (150) ──────9min──────────┘
```

## 🎯 System Features

### 🛫 Flight Data Integration
- **Real-time API Data**: Pulls actual flight departures/arrivals from OpenSky, AviationStack, AirLabs
- **Smart Booking Generation**: Creates realistic valet customers based on flight patterns
- **Fallback to Mock Data**: Works without API keys for development
- **Icelandic Traffic Patterns**: Models Keflavík's typical departure waves and seasonal patterns

### ⚡ Mathematical Optimization (GurobiPy)
- **Staff Scheduling**: Optimize number of staff per time period
- **Car Assignment**: Decide Gull vs P3 storage for each car
- **Movement Timing**: Schedule all car movements to minimize staff cost
- **Constraint Satisfaction**: Guarantee all cars ready on time
- **Capacity Management**: Respect zone limits and staff availability
- **Fallback Heuristics**: Works without Gurobi license

### 🎲 Discrete-Event Simulation (SimPy)
- **Stochastic Validation**: Test optimization under realistic uncertainty
- **Flight Delays**: Model customer arrival/return time variability
- **Driving Time Variance**: Traffic, weather, human factors
- **Resource Contention**: Limited staff and parking spaces
- **KPI Analysis**: Service level, utilization, wait times, violations
- **Monte Carlo**: Multiple runs for statistical confidence

### 🌐 Web Interface
- **3-Step Workflow**: Generate → Optimize → Simulate
- **Real-time Status**: System health monitoring
- **Interactive Dashboard**: Visual zone layout and results
- **Results Export**: Download optimization/simulation data
- **Responsive Design**: Works on all devices

## 🏗️ Architecture

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   External      │    │   Flask Web      │    │   GurobiPy      │
│   Flight APIs   │◄──►│   Application    │◄──►│   Optimizer     │
│   OpenSky/etc.  │    │                  │    │                 │
└─────────────────┘    └─────────┬────────┘    └─────────────────┘
                                 │                        ▲
                                 ▼                        │
┌─────────────────┐    ┌──────────────────┐              │
│   SimPy         │◄──►│   Frontend       │              │
│   Simulation    │    │   HTML/CSS/JS    │──────────────┘
│   Engine        │    │   Bootstrap      │
└─────────────────┘    └──────────────────┘
```

## 🚀 Quick Start

### Prerequisites
- Python 3.8+
- pip package manager
- Optional: Gurobi license (falls back to heuristics)
- Optional: Aviation API keys (uses mock data otherwise)

### Installation

1. **Clone repository**:
   ```bash
   git clone https://github.com/RiaanPhoenix/Emil_Isavia.git
   cd Emil_Isavia
   ```

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure environment** (optional):
   ```bash
   cp .env.example .env
   # Edit .env with your API keys
   ```

4. **Run the application**:
   ```bash
   python app.py
   ```

5. **Open browser**: http://localhost:5000

### Using the System

#### Step 1: Generate Bookings
- Set date and number of customers (default: 60)
- System pulls real flight data and creates valet bookings
- Each booking = customer drop-off time + return time

#### Step 2: Run Optimization  
- GurobiPy solves the staff scheduling problem
- Decides which storage zone for each car
- Plans all movements to minimize total staff time
- Guarantees cars ready ≥15 min before customer return

#### Step 3: Run Simulation
- SimPy tests the plan under stochastic conditions
- Adds flight delays, driving time variance
- Reports service level, violations, recommendations
- Multiple runs provide statistical confidence

## ⚙️ Configuration

### API Settings
```python
# Flight data providers
FLIGHT_API_PROVIDER = "opensky"  # opensky, aviationstack, airlabs
FLIGHT_API_KEY = ""              # Required for paid APIs

# Airport
AIRPORT_ICAO = "BIKF"            # Keflavík International
```

### Physical Parameters
```python
# Zone capacities
CAPACITY_RECEPTION = 14
CAPACITY_GULL = 50
CAPACITY_P3 = 150  
CAPACITY_DELIVERY = 20

# Travel times (minutes)
TRAVEL_RECEPTION_TO_GULL = 3     # + 5 min walk back
TRAVEL_RECEPTION_TO_P3 = 8       # + 12 min walk back
TRAVEL_GULL_TO_DELIVERY = 4      # + 6 min walk back
TRAVEL_P3_TO_DELIVERY = 9        # + 13 min walk back
```

### Optimization Settings
```python
# Operational constraints
DELIVERY_LEAD_TIME = 15          # Minutes before customer return
TIME_SLOT_MINUTES = 15          # Optimization granularity
PLANNING_HORIZON_H = 24         # Hours to optimize
MAX_STAFF = 10                  # Available staff limit
```

### Simulation Parameters
```python
SIM_RUNS = 10                   # Monte Carlo runs
SIM_FLIGHT_DELAY_STD = 15       # Flight delay std dev (min)
SIM_DRIVE_TIME_STD = 0.15      # Driving time variability
```

## 📊 API Endpoints

### Core Operations
```http
GET  /api/bookings              # Generate valet bookings
POST /api/optimize              # Run optimization model  
POST /api/simulate              # Run simulation
GET  /api/status                # System health check
```

### Example API Usage
```javascript
// Generate bookings
fetch('/api/bookings?date=2024-12-01&customers=60')

// Run optimization
fetch('/api/optimize', {
  method: 'POST',
  body: JSON.stringify({
    bookings: [...],
    base_time: '2024-12-01T00:00:00'
  })
})

// Run simulation
fetch('/api/simulate', {
  method: 'POST', 
  body: JSON.stringify({
    bookings: [...],
    optimization_plan: {...},
    n_runs: 10
  })
})
```

## 📈 KPIs & Metrics

### Optimization Results
- **Staff Hours**: Total staff time required
- **Car Movements**: Number of scheduled moves
- **Zone Utilization**: Peak occupancy by zone
- **Solution Status**: Optimal/heuristic/infeasible

### Simulation Results  
- **Service Level**: % cars ready on time (target: ≥95%)
- **Customer Wait Time**: Avg minutes (negative = ready early)
- **Staff Utilization**: Actual vs planned usage
- **Violations**: Service failures and capacity overflows
- **Recommendations**: Operational improvements

## 🐳 Docker Deployment

```bash
# Build image
docker build -t emil-isavia .

# Run container
docker run -p 5000:5000 \
  -e ISAVIA_FLIGHT_API_KEY=your_key \
  -e ISAVIA_MAX_STAFF=12 \
  emil-isavia
```

### Production with Gunicorn
```bash
gunicorn --bind 0.0.0.0:5000 --workers 4 --timeout 120 app:app
```

## 🧪 Development

### Project Structure
```
Emil_Isavia/
├── app/
│   ├── api/
│   │   └── flights.py          # Flight data integration
│   ├── optimization/
│   │   └── valet_optimizer.py  # GurobiPy models
│   ├── simulation/
│   │   └── valet_sim.py        # SimPy simulation
│   ├── static/
│   │   ├── css/style.css
│   │   └── js/main.js
│   └── templates/
│       ├── base.html
│       ├── index.html
│       ├── optimize.html
│       └── simulate.html
├── config/
│   └── settings.py             # Configuration
├── app.py                      # Main Flask app
├── requirements.txt            # Dependencies
└── README.md                   # This file
```

### Running Tests
```bash
pytest tests/                   # Unit tests
python -m pytest --cov=app    # Coverage report
```

### Code Quality
```bash
black app/                     # Format code
flake8 app/                    # Lint code
```

## 🎯 Use Cases

### Airport Operations
- **Daily Planning**: Optimize staff schedules for next day
- **Peak Period Management**: Handle morning departure rushes
- **Capacity Analysis**: Evaluate zone expansion scenarios
- **Service Level Monitoring**: Track KPIs and customer satisfaction

### Strategic Planning  
- **Staffing Decisions**: How many staff needed for growth?
- **Infrastructure Investment**: Should P3 be expanded?
- **Service Improvements**: Impact of reducing delivery lead time
- **Cost Optimization**: Balance service level vs operational cost

### Research & Analysis
- **Stochastic Modeling**: Impact of flight delays on operations
- **Sensitivity Analysis**: Critical system parameters
- **Scenario Testing**: COVID, seasonal variations, events
- **Benchmarking**: Compare optimization vs current practice

## 🏆 Results & Benefits

### Efficiency Gains
- **Reduced Staff Cost**: Optimal scheduling vs ad-hoc decisions
- **Higher Utilization**: Better zone and resource utilization
- **Improved Service**: Systematic approach to meeting deadlines
- **Risk Mitigation**: Proactive identification of bottlenecks

### Decision Support
- **Data-Driven Operations**: Replace intuition with optimization
- **Scenario Planning**: Test "what-if" questions safely
- **Performance Monitoring**: Continuous improvement through KPIs
- **Investment Justification**: Quantify benefits of expansion

## 📚 Technical Details

### Optimization Model
- **Variables**: Car locations, movements, staff levels by time slot
- **Objective**: Minimize total staff-hours
- **Constraints**: Capacity limits, movement timing, service deadlines
- **Algorithm**: Mixed-integer linear programming (MILP)
- **Solver**: Gurobi (commercial) with heuristic fallback

### Simulation Model
- **Paradigm**: Discrete-event simulation with SimPy
- **Stochasticity**: Normal distributions for delays/variability
- **Resources**: Staff (limited), zones (capacitated)
- **Processes**: Customer arrivals, car movements, pickups
- **Output**: Service statistics, utilization, violation logs

## 🔧 Troubleshooting

### Common Issues

**Gurobi License Error**
```
Error: No Gurobi license found
Solution: System will use heuristic algorithms automatically
```

**API Rate Limiting**
```  
Error: Flight API rate limit exceeded
Solution: Reduce booking frequency or use mock data
```

**High Service Level Violations**
```
Problem: <95% cars ready on time in simulation
Solution: Increase staff, adjust lead time, or expand zones
```

## 📄 License & Support

### License
MIT License - see LICENSE file for details

### Contributing
1. Fork the repository
2. Create feature branch (`git checkout -b feature/improvement`)
3. Commit changes (`git commit -am 'Add improvement'`)
4. Push to branch (`git push origin feature/improvement`)  
5. Create Pull Request

### Support
- **Issues**: GitHub issue tracker
- **Documentation**: This README + code comments
- **Community**: Contributions welcome

---

**Emil Isavia** — Optimizing Premium valet operations at Keflavík Airport through data-driven mathematical modeling.

Built with ❤️ for Isavia and the Icelandic aviation industry.