#!/usr/bin/env python
"""
Azure SQL Server Connection Test Script
Run this on your Azure App Service to test database connectivity.
"""

import os
import sys
import django
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
    print(f"Driver: {db_config['OPTIONS']['driver']}")
    print()
    
    # Build connection string
    conn_str = (
        f"DRIVER={{{db_config['OPTIONS']['driver']}}};"
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
        
        conn.close()
        print("✅ Connection closed successfully!")
        return True
        
    except pyodbc.Error as e:
        print(f"❌ PyODBC Error: {e}")
        print(f"Error Code: {e.args[0] if e.args else 'Unknown'}")
        return False
    except Exception as e:
        print(f"❌ General Error: {e}")
        return False


def test_django_connection():
    """Test connection through Django ORM."""
    print("\n🔍 Testing Django ORM Connection")
    print("=" * 50)
    
    try:
        from django.db import connection
        
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            result = cursor.fetchone()
            
            if result and result[0] == 1:
                print("✅ Django ORM connection successful!")
                
                # Get database info
                cursor.execute("SELECT @@VERSION")
                version = cursor.fetchone()[0]
                print(f"✅ SQL Server version: {version[:50]}...")
                
                return True
            else:
                print("❌ Django ORM query returned unexpected result")
                return False
                
    except Exception as e:
        print(f"❌ Django ORM Error: {e}")
        return False


def check_environment():
    """Check environment variables."""
    print("\n🔍 Checking Environment Variables")
    print("=" * 50)
    
    required_vars = ['DB_NAME', 'DB_USER', 'DB_PASSWORD', 'DB_HOST']
    missing_vars = []
    
    for var in required_vars:
        value = os.environ.get(var)
        if value:
            # Mask password for security
            display_value = "***" if var == 'DB_PASSWORD' else value
            print(f"✅ {var}: {display_value}")
        else:
            print(f"❌ {var}: Not set")
            missing_vars.append(var)
    
    if missing_vars:
        print(f"\n❌ Missing environment variables: {', '.join(missing_vars)}")
        return False
    else:
        print("\n✅ All required environment variables are set")
        return True


def main():
    """Run all connection tests."""
    print("🚀 Azure SQL Server Connection Diagnostic Tool")
    print("=" * 60)
    print()
    
    # Check if running on Azure
    if os.environ.get('WEBSITE_SITE_NAME'):
        print(f"✅ Running on Azure App Service: {os.environ.get('WEBSITE_SITE_NAME')}")
    else:
        print("⚠️  Not running on Azure App Service")
    print()
    
    # Run tests
    env_ok = check_environment()
    direct_ok = test_direct_connection()
    django_ok = test_django_connection()
    
    print("\n" + "=" * 60)
    print("📊 TEST SUMMARY")
    print("=" * 60)
    print(f"Environment Variables: {'✅ PASS' if env_ok else '❌ FAIL'}")
    print(f"Direct Connection: {'✅ PASS' if direct_ok else '❌ FAIL'}")
    print(f"Django ORM: {'✅ PASS' if django_ok else '❌ FAIL'}")
    
    if all([env_ok, direct_ok, django_ok]):
        print("\n🎉 All tests passed! Database connection is working correctly.")
    else:
        print("\n💥 Some tests failed. Check the troubleshooting guide:")
        print("📖 See AZURE_SQL_TROUBLESHOOTING.md for detailed fixes")


if __name__ == '__main__':
    main()
