from django import template
import ssl
import socket
import OpenSSL
from django.conf import settings
from django.core.cache import cache
from datetime import datetime, timedelta

register = template.Library()

@register.simple_tag(takes_context=True)
def is_cert_untrusted(context):
    """
    Check if the certificate is untrusted by attempting to verify the connection.
    Uses caching to prevent frequent rechecks and fluctuating results.
    """
    request = context['request']
    
    # If not HTTPS, no certificate issues
    if not request.is_secure():
        return False

    # Get hostname for cache key
    hostname = request.get_host().split(':')[0]
    cache_key = f'cert_status_{hostname}'
    
    # Check cache first
    cached_status = cache.get(cache_key)
    if cached_status is not None:
        return cached_status

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
                        cache.set(cache_key, True, 300)  # Cache for 5 minutes
                        return True
                
                # Certificate is valid
                cache.set(cache_key, False, 300)  # Cache for 5 minutes
                return False
                
    except (ssl.SSLError, ssl.CertificateError, socket.error, ValueError, KeyError) as e:
        # Log the error for debugging
        print(f"Certificate verification failed: {str(e)}")
        cache.set(cache_key, True, 300)  # Cache for 5 minutes
        return True
    
    # Default to showing the error if verification fails
    cache.set(cache_key, True, 300)  # Cache for 5 minutes
    return True
