#!/usr/bin/env python
"""
Azure SQL Server Connection Test Script
Run this on your Azure App Service to test database connectivity.
"""

import os
import sys
import django
import pytest
from pathlib import Path

# Add the project directory to Python path
project_dir = Path(__file__).parent
sys.path.insert(0, str(project_dir))

# Set up Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'STATZWeb.settings')
django.setup()

from django.conf import settings
import pyodbc


def test_direct_connection():
    """Test direct connection to Azure SQL Server using pyodbc."""
    print("🔍 Testing Direct Azure SQL Server Connection")
    print("=" * 50)
    
    # Get database configuration
    db_config = settings.DATABASES['default']
    
    print(f"Server: {db_config['HOST']}")
    print(f"Database: {db_config['NAME']}")
    print(f"User: {db_config['USER']}")
    options = db_config.get('OPTIONS', {})
    driver = options.get('driver')

    if not driver:
        pytest.skip("Azure SQL Server driver not configured; skipping direct connection test.")

    print(f"Driver: {driver}")
    print()
    
    # Build connection string
    conn_str = (
        f"DRIVER={{{driver}}};"
        f"SERVER={db_config['HOST']};"
        f"DATABASE={db_config['NAME']};"
        f"UID={db_config['USER']};"
        f"PWD={db_config['PASSWORD']};"
        f"Encrypt=yes;"
        f"TrustServerCertificate=no;"
        f"Connection Timeout=30;"
    )
    
    try:
        print("Attempting connection...")
        conn = pyodbc.connect(conn_str, timeout=30)
        print("✅ Connection successful!")
        
        # Test a simple query
        cursor = conn.cursor()
        cursor.execute("SELECT @@VERSION")
        version = cursor.fetchone()[0]
        print(f"✅ Query successful! SQL Server version: {version[:50]}...")
        
        # Test table access
        cursor.execute("SELECT COUNT(*) FROM information_schema.tables")
        table_count = cursor.fetchone()[0]
        print(f"✅ Database accessible! Found {table_count} tables.")