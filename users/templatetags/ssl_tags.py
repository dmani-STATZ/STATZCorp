from django import template
import ssl
import socket
import OpenSSL
import subprocess
import platform
import os
from django.conf import settings
from django.core.cache import cache
from datetime import datetime, timedelta

register = template.Library()

def check_windows_cert_store(hostname):
    """Check if the certificate is trusted in Windows certificate store"""
    try:
        # Use PowerShell to check certificate in Windows store
        ps_command = f'Get-ChildItem -Path Cert:\\CurrentUser\\Root -Recurse | Where-Object {{ $_.Subject -like "*{hostname}*" -or $_.Issuer -like "*{hostname}*" }}'
        result = subprocess.run(['powershell', '-Command', ps_command], 
                              capture_output=True, 
                              text=True)
        return bool(result.stdout.strip())
    except Exception as e:
        print(f"Failed to check Windows certificate store: {str(e)}")
        return False

@register.simple_tag(takes_context=True)
def is_cert_untrusted(context):
    """
    Check if the certificate is untrusted by:
    1. Checking Windows certificate store
    2. Attempting direct SSL connection
    3. Verifying certificate dates
    """
    request = context['request']
    
    # If not HTTPS, no certificate issues
    if not request.is_secure():
        return False

    # Get hostname for cache key
    hostname = request.get_host().split(':')[0]
    cache_key = f'cert_status_{hostname}'
    
    # If we have cert_refresh parameter in URL or cert_installed in session, bypass cache
    cert_refresh = request.GET.get('cert_refresh') is not None
    
    # If refresh requested, invalidate cache
    if cert_refresh:
        cache.delete(cache_key)
    # Otherwise check cache
    else:
        cached_status = cache.get(cache_key)
        if cached_status is not None:
            return cached_status

    # First check Windows certificate store
    if check_windows_cert_store(hostname):
        cache.set(cache_key, False, 300)  # Cache for 5 minutes
        return False

    try:
        # Create an SSL context with strict verification
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = True
        ssl_context.verify_mode = ssl.CERT_REQUIRED
        
        # Try to establish a connection
        with socket.create_connection((hostname, 443), timeout=5) as sock:
            with ssl_context.wrap_socket(sock, server_hostname=hostname) as ssock:
                cert = ssock.getpeercert()
                
                # Verify certificate dates
                if cert:
                    not_after = datetime.strptime(cert['notAfter'], '%b %d %H:%M:%S %Y %Z')
                    not_before = datetime.strptime(cert['notBefore'], '%b %d %H:%M:%S %Y %Z')
                    now = datetime.utcnow()
                    
                    if now < not_before or now > not_after:
                        print(f"Certificate date validation failed for {hostname}")
                        cache.set(cache_key, True, 300)
                        return True
                
                # Certificate is valid
                cache.set(cache_key, False, 300)
                return False
                
    except (ssl.SSLError, ssl.CertificateError, socket.error, ValueError, KeyError) as e:
        # Log the error for debugging
        print(f"Certificate verification failed for {hostname}: {str(e)}")
        cache.set(cache_key, True, 300)
        return True
    
    # Default to showing the error if verification fails
    cache.set(cache_key, True, 300)
    return True
