from django import template
import ssl
import socket
import OpenSSL
from django.conf import settings

register = template.Library()

@register.simple_tag(takes_context=True)
def is_cert_untrusted(context):
    """
    Check if the certificate is untrusted by attempting to verify the connection
    """
    request = context['request']
    
    # If not HTTPS, no certificate issues
    if not request.is_secure():
        return False
        
    try:
        # Get the hostname from the request
        hostname = request.get_host().split(':')[0]
        
        # Create an SSL context with strict verification
        context = ssl.create_default_context()
        
        # Try to establish a connection
        with socket.create_connection((hostname, 443)) as sock:
            with context.wrap_socket(sock, server_hostname=hostname) as ssock:
                cert = ssock.getpeercert()
                return False  # Certificate is trusted
    except (ssl.SSLError, ssl.CertificateError, socket.error):
        return True  # Certificate is untrusted or connection failed
    
    return True  # Default to showing the error if verification fails
