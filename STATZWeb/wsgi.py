"""
WSGI config for STATZWeb project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.1/howto/deployment/wsgi/
"""

import os
import sys
import traceback

# Add debugging output
try:
    # Print environment info to help with debugging
    #print("Python version:", sys.version)
    #print("Python path:", sys.path)
    #print("Current directory:", os.getcwd())
    
    # Load environment variables from .env.production
    from pathlib import Path
    from dotenv import load_dotenv
    
    # Build paths inside the project
    BASE_DIR = Path(__file__).resolve().parent.parent
    env_file = os.path.join(BASE_DIR, '.env.production')
    #print(f"Loading environment from: {env_file}")
    load_dotenv(env_file)
    #print(f"SECRET_KEY loaded: {'DJANGO_SECRET_KEY' in os.environ}")
    
    from django.core.wsgi import get_wsgi_application
    
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'STATZWeb.settings_prod')
    
    # Add basic error handling
    try:
        application = get_wsgi_application()
        #print("WSGI application initialized successfully")
    except Exception as e:
        #print("Error initializing WSGI application:", str(e))
        #print(traceback.format_exc())
        # Fallback to a simple application for diagnostics
        def simple_app(environ, start_response):
            status = '500 Internal Server Error'
            headers = [('Content-type', 'text/plain; charset=utf-8')]
            start_response(status, headers)
            error_msg = f"Error initializing Django application: {str(e)}\n\n{traceback.format_exc()}"
            return [error_msg.encode('utf-8')]
        application = simple_app
        
except Exception as e:
    #print("Error in WSGI file:", str(e))
    #print(traceback.format_exc())
    # Provide a minimal working application for diagnosis
    def minimal_app(environ, start_response):
        status = '200 OK'
        headers = [('Content-type', 'text/plain; charset=utf-8')]
        start_response(status, headers)
        return [b"Minimal WSGI application is working. Error in main application."]
    application = minimal_app
