#!/usr/bin/env python
"""
Development commands for STATZWeb.
This script provides easy commands for development workflow.
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
    """Main command handler."""
    if len(sys.argv) < 2:
        print("🚀 STATZWeb Development Commands")
        print("\nUsage: python dev_commands.py <command>")
        print("\nAvailable commands:")
        print("  start     - Start development server")
        print("  stop      - Stop development server")
        print("  restart   - Restart development server")
        print("  migrate   - Run database migrations")
        print("  superuser - Create superuser account")
        print("  no-login  - Start server without login requirement")
        print("  with-login- Start server with login requirement")
        print("  check     - Check Django configuration")
        print("  shell     - Open Django shell")
        print("  help      - Show this help message")
        return

    command = sys.argv[1].lower()
    
    if command == "start":
        print("🚀 Starting development server...")
        print("📝 Server will be available at: http://127.0.0.1:8000")
        print("🔐 Login is required by default")
        print("💡 Use 'python dev_commands.py no-login' to bypass login")
        print("🛑 Press Ctrl+C to stop the server")
        run_command("python manage.py runserver 127.0.0.1:8000", "Starting development server")
        
    elif command == "no-login":
        print("🚀 Starting development server WITHOUT login requirement...")
        print("📝 Server will be available at: http://127.0.0.1:8000")
        print("⚠️  Login is DISABLED - anyone can access the app")
        print("🛑 Press Ctrl+C to stop the server")
        os.environ['REQUIRE_LOGIN'] = 'False'
        run_command("python manage.py runserver 127.0.0.1:8000", "Starting development server (no login)")
        
    elif command == "with-login":
        print("🚀 Starting development server WITH login requirement...")
        print("📝 Server will be available at: http://127.0.0.1:8000")
        print("🔐 Login is REQUIRED")
        print("🛑 Press Ctrl+C to stop the server")
        os.environ['REQUIRE_LOGIN'] = 'True'
        run_command("python manage.py runserver 127.0.0.1:8000", "Starting development server (with login)")
        
    elif command == "migrate":
        run_command("python manage.py migrate", "Running database migrations")
        
    elif command == "superuser":
        run_command("python manage.py createsuperuser", "Creating superuser account")
        
    elif command == "check":
        run_command("python manage.py check", "Checking Django configuration")
        
    elif command == "shell":
        print("🐍 Opening Django shell...")
        print("💡 Use 'exit()' to quit the shell")
        run_command("python manage.py shell", "Opening Django shell")
        
    elif command == "help":
        print("🚀 STATZWeb Development Commands")
        print("\nUsage: python dev_commands.py <command>")
        print("\nAvailable commands:")
        print("  start     - Start development server (with login)")
        print("  no-login  - Start server without login requirement")
        print("  with-login- Start server with login requirement")
        print("  migrate   - Run database migrations")
        print("  superuser - Create superuser account")
        print("  check     - Check Django configuration")
        print("  shell     - Open Django shell")
        print("  help      - Show this help message")
        
    else:
        print(f"❌ Unknown command: {command}")
        print("💡 Use 'python dev_commands.py help' to see available commands")

if __name__ == "__main__":
    main()
