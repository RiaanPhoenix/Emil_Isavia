# Emil Isavia - Aviation Traffic Optimization System

A comprehensive web application that integrates external aviation API data with optimization and simulation models for flight traffic management at Icelandic airports (primarily Keflavik International - BIKF).

## Features

### 🛫 Flight Data Integration
- **Multiple API Support**: AviationStack, OpenSky Network, AirLabs
- **Real-time Data**: Fetches current flight schedules, delays, and status
- **Mock Data Fallback**: Works without API keys for development/testing
- **Data Processing**: Automatic parsing and formatting of aviation data

### ⚡ Optimization Engine (GurobiPy)
- **Flight Scheduling**: Optimal slot allocation for departures/arrivals
- **Premium Pricing**: Dynamic pricing optimization with demand-based tiers
- **Capacity Management**: Runway, gate, and resource constraint optimization
- **Revenue Maximization**: Multi-objective optimization for airline revenue
- **Fallback Algorithms**: Heuristic optimization when Gurobi is unavailable

### 🎯 Airport Simulation (SimPy)
- **Discrete Event Simulation**: Complete airport operations modeling
- **Passenger Flow**: Check-in, security, boarding processes
- **Ground Operations**: Baggage, fueling, catering, cleaning
- **Resource Utilization**: Gates, runways, staff, equipment tracking
- **Bottleneck Analysis**: Automated identification of operational constraints
- **Performance Metrics**: Turnaround times, utilization rates, recommendations

### 🌐 Web Interface
- **Interactive Dashboard**: Real-time system overview and status
- **Optimization Controls**: Parameter adjustment and execution
- **Simulation Controls**: Configuration and results visualization
- **Data Tables**: Flight schedules and operational data
- **Charts & Analytics**: Visual performance indicators
- **Responsive Design**: Works on desktop, tablet, and mobile

## System Architecture

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   External      │    │   Flask Web      │    │   Optimization  │
│   Aviation APIs │◄──►│   Application    │◄──►│   & Simulation  │
└─────────────────┘    └──────────────────┘    └─────────────────┘
                               ▲
                               │
                    ┌──────────▼──────────┐
                    │   Frontend (HTML/   │
                    │   CSS/JS/Charts)    │
                    └─────────────────────┘
```

## Installation & Setup

### Prerequisites
- Python 3.8+
- pip (Python package manager)
- Optional: Gurobi license (for optimization)
- Optional: Aviation API keys

### Quick Start

1. **Clone the repository**:
   ```bash
   git clone https://github.com/RiaanPhoenix/Emil_Isavia.git
   cd Emil_Isavia
   ```

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Set up environment variables** (optional):
   ```bash
   # Create .env file
   echo "AVIATIONSTACK_API_KEY=your_api_key_here" > .env
   echo "AIRLABS_API_KEY=your_api_key_here" >> .env
   echo "SECRET_KEY=your_secret_key_here" >> .env
   ```

4. **Run the application**:
   ```bash
   python app.py
   ```

5. **Open your browser** and navigate to `http://localhost:5000`

### Docker Setup (Alternative)

```bash
# Build Docker image
docker build -t emil-isavia .

# Run container
docker run -p 5000:5000 emil-isavia
```

## Configuration

### API Configuration
The system supports multiple aviation data providers:

- **AviationStack**: Comprehensive flight data (requires API key)
- **OpenSky Network**: Open flight tracking data (free, no key required)
- **AirLabs**: Flight schedules and real-time data (requires API key)

### Airport Configuration
Default settings for Keflavik International Airport (BIKF):
- 2 runways
- 12 gates  
- 48 daily slots (30-minute intervals)
- Various ground resources (fuel trucks, catering, etc.)

### Optimization Settings
- **GurobiPy**: Professional optimization solver (requires license)
- **Fallback**: Heuristic algorithms when Gurobi unavailable
- **Constraints**: Runway capacity, turnaround times, premium slots
- **Objectives**: Revenue maximization, slot utilization

### Simulation Parameters
- **Duration**: Configurable simulation time (default: 24 hours)
- **Passenger Flow**: Check-in windows, security processing times
- **Ground Operations**: Service times for various airport functions
- **Resources**: Staff, equipment, and facility capacity

## API Endpoints

### Core Endpoints
- `GET /` - Main dashboard
- `GET /api/flights` - Fetch flight data
- `GET /api/status` - System health check
- `POST /optimize` - Run optimization model
- `POST /simulate` - Run simulation model

### Parameters
```javascript
// Flight data request
GET /api/flights?airport=BIKF&hours=24

// Optimization request
POST /optimize
{
  "flights": [...],
  "capacity_constraints": {...},
  "pricing_tiers": {...}
}

// Simulation request  
POST /simulate
{
  "flights": [...],
  "airport_config": {...},
  "duration": 24
}
```

## Development

### Project Structure
```
Emil_Isavia/
├── app.py                 # Main Flask application
├── config/
│   └── settings.py        # Configuration settings
├── src/
│   ├── api/
│   │   └── flight_data.py # API integration
│   ├── optimization/
│   │   └── flight_optimizer.py # GurobiPy optimization
│   └── simulation/
│       └── airport_simulator.py # SimPy simulation
├── templates/             # HTML templates
├── static/               # CSS, JavaScript, images
├── data/                 # Data storage
├── requirements.txt      # Python dependencies
└── README.md            # This file
```

### Adding New Features

1. **New API Provider**:
   - Add provider setup in `src/api/flight_data.py`
   - Implement data parsing method
   - Update configuration

2. **New Optimization Objective**:
   - Extend `FlightOptimizer` class
   - Add constraints and variables
   - Update web interface

3. **New Simulation Element**:
   - Add process to `AirportSimulator`
   - Define resource requirements
   - Include in results analysis

### Testing

```bash
# Run tests (when implemented)
pytest tests/

# Check code style
black src/ --check
flake8 src/
```

## Production Deployment

### Using Gunicorn
```bash
# Install gunicorn (included in requirements.txt)
pip install gunicorn

# Run production server
gunicorn --bind 0.0.0.0:5000 --workers 4 app:app
```

### Environment Variables
```bash
export ENVIRONMENT=production
export SECRET_KEY=your-production-secret-key
export AVIATIONSTACK_API_KEY=your-api-key
export GUROBI_LICENSE_FILE=/path/to/gurobi.lic
```

### Monitoring
- Application logs: `logs/emil_isavia.log`
- System status: `/api/status` endpoint
- Performance metrics via simulation results

## Use Cases

### Airlines
- **Route Optimization**: Maximize revenue through optimal scheduling
- **Premium Pricing**: Identify high-demand slots for premium pricing
- **Fleet Management**: Optimize aircraft utilization and turnaround times

### Airports
- **Capacity Planning**: Analyze bottlenecks and resource requirements
- **Slot Allocation**: Fair and efficient runway/gate assignment
- **Performance Monitoring**: Track KPIs and operational efficiency

### Aviation Authorities
- **Traffic Management**: System-wide optimization of air traffic flow
- **Policy Analysis**: Simulate impact of regulatory changes
- **Emergency Planning**: Model disruption scenarios and recovery

## Technical Requirements

### Minimum System Requirements
- **CPU**: 2+ cores recommended for simulation
- **RAM**: 4GB minimum, 8GB recommended
- **Storage**: 1GB for application and data
- **Network**: Internet connection for API data

### Recommended Setup
- **CPU**: 4+ cores for complex optimizations
- **RAM**: 16GB for large-scale simulations
- **Storage**: SSD for better performance
- **OS**: Linux/macOS for best Gurobi performance

## License & Support

### License
This project is licensed under the MIT License - see the LICENSE file for details.

### Support
- **Issues**: GitHub issue tracker
- **Documentation**: This README and inline code comments
- **Community**: Contributions welcome via pull requests

### Contributing
1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests (if applicable)
5. Submit a pull request

## Roadmap

### Phase 1 (Current)
- ✅ Basic web interface
- ✅ API integration
- ✅ GurobiPy optimization
- ✅ SimPy simulation

### Phase 2 (Planned)
- [ ] Database integration
- [ ] User authentication
- [ ] Advanced analytics
- [ ] Real-time updates

### Phase 3 (Future)
- [ ] Machine learning predictions
- [ ] Multi-airport optimization
- [ ] Mobile application
- [ ] API for third-party integration

---

**Emil Isavia** - Optimizing Icelandic aviation through data-driven decision making.