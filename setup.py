#!/usr/bin/env python3
"""
Emil Isavia - Setup Script for Premium Valet Parking System

Quick installation and verification script for the Isavia
valet parking optimization system.
"""

import os
import sys
import subprocess
import shutil
from pathlib import Path

def print_header():
    print("=" * 60)
    print("🚗 Emil Isavia - Premium Valet Parking System")
    print("=" * 60)
    print()
    print("Setting up optimization & simulation for Keflavík Airport")
    print("valet parking operations...")
    print()

def check_python_version():
    """Check Python version compatibility"""
    version = sys.version_info
    if version.major < 3 or (version.major == 3 and version.minor < 8):
        print("❌ Error: Python 3.8 or higher required")
        print(f"   Current: Python {version.major}.{version.minor}.{version.micro}")
        sys.exit(1)
    print(f"✅ Python {version.major}.{version.minor}.{version.micro}")

def check_pip():
    """Check if pip is available"""
    try:
        subprocess.run([sys.executable, "-m", "pip", "--version"], 
                      check=True, capture_output=True)
        print("✅ pip available")
        return True
    except subprocess.CalledProcessError:
        print("❌ pip not available")
        return False

def install_dependencies():
    """Install required Python packages"""
    print("\n📦 Installing dependencies...")
    
    try:
        # Essential packages that must work
        essential_packages = [
            "Flask==2.3.3",
            "requests==2.31.0", 
            "numpy==1.24.3",
            "simpy==4.0.2",
            "python-dotenv==1.0.0",
            "python-dateutil==2.8.2"
        ]
        
        subprocess.run([sys.executable, "-m", "pip", "install"] + essential_packages,
                      check=True)
        print("✅ Essential packages installed")
        
        # Try to install Gurobi (optional)
        try:
            subprocess.run([sys.executable, "-m", "pip", "install", "gurobipy"],
                          check=True, capture_output=True)
            print("✅ GurobiPy installed (requires license)")
        except subprocess.CalledProcessError:
            print("⚠️  GurobiPy not installed (will use heuristic fallback)")
        
        return True
        
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to install dependencies: {e}")
        return False

def create_directories():
    """Create required directories"""
    print("\n📁 Creating directories...")
    
    directories = [
        "data",
        "logs", 
        "app/static/uploads"
    ]
    
    for directory in directories:
        Path(directory).mkdir(parents=True, exist_ok=True)
        print(f"   ✓ {directory}/")
    
    print("✅ Directories created")

def setup_environment():
    """Set up environment configuration"""
    print("\n🔧 Setting up configuration...")
    
    if not Path(".env").exists():
        # Create basic .env file
        env_content = """# Emil Isavia - Premium Valet Parking Configuration

# Flask settings
ISAVIA_SECRET_KEY=dev-change-this-in-production
ISAVIA_DEBUG=true
ISAVIA_PORT=5000

# External flight API (optional - uses mock data if not provided)
ISAVIA_FLIGHT_API_PROVIDER=opensky
ISAVIA_FLIGHT_API_KEY=

# Airport configuration
ISAVIA_AIRPORT_ICAO=BIKF
ISAVIA_MAX_STAFF=10

# Operational parameters
ISAVIA_DELIVERY_LEAD=15
ISAVIA_HORIZON_H=24

# Simulation settings  
ISAVIA_SIM_RUNS=10
ISAVIA_SIM_SEED=42
"""
        
        with open(".env", "w") as f:
            f.write(env_content)
        print("✅ .env configuration file created")
    else:
        print("✅ .env file already exists")

def test_imports():
    """Test critical package imports"""
    print("\n🧪 Testing imports...")
    
    tests = [
        ("Flask", "flask"),
        ("Requests", "requests"),
        ("NumPy", "numpy"),
        ("SimPy", "simpy"),
        ("Python-dotenv", "dotenv")
    ]
    
    for name, module in tests:
        try:
            __import__(module)
            print(f"   ✅ {name}")
        except ImportError:
            print(f"   ❌ {name} - import failed")
            return False
    
    # Test optional Gurobi
    try:
        import gurobipy
        print("   ✅ GurobiPy (optimization solver)")
    except ImportError:
        print("   ⚠️  GurobiPy not available (will use heuristic)")
    
    print("✅ Import tests passed")
    return True

def test_application():
    """Basic application test"""
    print("\n🚀 Testing application startup...")
    
    try:
        # Import main application components
        sys.path.insert(0, '.')
        from app.api.flights import generate_bookings_from_api
        from app.optimization.valet_optimizer import ValetOptimizer
        from app.simulation.valet_sim import ValetSimulation
        
        # Test booking generation (mock data)
        bookings = generate_bookings_from_api(n_premium_customers=5)
        if bookings:
            print(f"   ✅ Generated {len(bookings)} test bookings")
        
        # Test optimizer initialization
        optimizer = ValetOptimizer()
        print("   ✅ Optimizer initialized")
        
        # Test simulation initialization  
        sim = ValetSimulation()
        print("   ✅ Simulator initialized")
        
        print("✅ Application components working")
        return True
        
    except Exception as e:
        print(f"   ❌ Application test failed: {e}")
        return False

def print_next_steps():
    """Show user what to do next"""
    print("\n" + "=" * 60)
    print("🎉 Setup Complete!")
    print("=" * 60)
    
    print("\n📋 Next Steps:")
    print()
    print("1. 🚀 Start the application:")
    print("   python app.py")
    print()
    print("2. 🌐 Open your browser:")
    print("   http://localhost:5000")
    print()
    print("3. 📊 Use the 3-step workflow:")
    print("   → Generate valet bookings")
    print("   → Run optimization")  
    print("   → Run simulation")
    print()
    print("4. ⚙️ Optional: Configure API keys in .env for real flight data")
    print()
    print("5. 🏭 Production deployment:")
    print("   gunicorn --bind 0.0.0.0:5000 app:app")
    print()
    print("📚 Documentation: README.md")
    print("🐛 Issues: https://github.com/RiaanPhoenix/Emil_Isavia/issues")
    print()

def main():
    """Main setup routine"""
    print_header()
    
    # System checks
    check_python_version()
    if not check_pip():
        sys.exit(1)
    
    # Installation
    if not install_dependencies():
        print("\n❌ Setup failed during dependency installation")
        sys.exit(1)
    
    create_directories()
    setup_environment()
    
    # Verification
    if not test_imports():
        print("\n⚠️  Setup completed with import warnings")
    
    if not test_application():
        print("\n⚠️  Setup completed but application test failed")
        print("   Try running: python app.py")
    
    print_next_steps()

if __name__ == "__main__":
    main()