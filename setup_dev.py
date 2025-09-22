#!/usr/bin/env python
"""
Development setup script for STATZWeb.
This script helps set up the development environment.
"""

import os
import sys
import subprocess
from pathlib import Path

def run_command(command, description):
    """Run a command and handle errors."""
    print(f"🔧 {description}...")
    try:
        result = subprocess.run(command, shell=True, check=True, capture_output=True, text=True)
        print(f"✅ {description} completed successfully")
        if result.stdout:
            print(result.stdout)
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ {description} failed:")
        print(f"Error: {e.stderr}")
        return False

def main():
    """Set up development environment."""
    print("🚀 Setting up STATZWeb development environment...")
    
    # Check if we're in the right directory
    if not Path("manage.py").exists():
        print("❌ Please run this script from the project root directory")
        sys.exit(1)
    
    # Create logs directory if it doesn't exist
    logs_dir = Path("logs")
    logs_dir.mkdir(exist_ok=True)
    
    # Create .env file from example if it doesn't exist
    env_file = Path(".env")
    env_example = Path("env.dev.example")
    
    if not env_file.exists() and env_example.exists():
        print("📝 Creating .env file from example...")
        with open(env_example, 'r') as src, open(env_file, 'w') as dst:
            dst.write(src.read())
        print("✅ .env file created")
    
    # Install development requirements
    if not run_command("pip install -r requirements-dev.txt", "Installing development requirements"):
        print("⚠️  Some packages might not have installed correctly")
    
    # Run migrations
    if not run_command("python manage.py migrate", "Running database migrations"):
        print("⚠️  Database migrations might have issues")
    
    # Create superuser (optional)
    print("\n🔐 Would you like to create a superuser? (y/n): ", end="")
    create_superuser = input().lower().strip()
    if create_superuser == 'y':
        run_command("python manage.py createsuperuser", "Creating superuser")
    
    # Collect static files
    if not run_command("python manage.py collectstatic --noinput", "Collecting static files"):
        print("⚠️  Static files collection might have issues")
    
    print("\n🎉 Development environment setup complete!")
    print("\n📋 Next steps:")
    print("1. Run: python manage.py runserver")
    print("2. Open: http://127.0.0.1:8000")
    print("3. For production deployment, use: DJANGO_SETTINGS_MODULE=STATZWeb.settings python manage.py runserver")

if __name__ == "__main__":
    main()
