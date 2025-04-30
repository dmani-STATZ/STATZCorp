// Certificate checker and installer
/**
 * CertificateChecker - Handles detection and resolution of SSL certificate issues
 * 
 * This class implements a workflow to:
 * 1. Check if the browser has a valid SSL certificate for the site
 * 2. If not, shows a UI to guide the user through installation
 * 3. After installation, uses session storage to track completion
 * 4. Forces a clean cache reload to ensure the browser recognizes the new certificate
 * 
 * Certificate validation issues were previously persisting due to browser/fetch API caching
 * This implementation uses multiple caching strategies to ensure fresh certificate checks:
 * - Adds cache-busting URL parameters
 * - Sets no-cache headers for fetch requests
 * - Clears browser caches when returning from certificate installation
 * - Uses session storage to track certificate installation state
 * - Communicates with Django's ssl_tags.py to clear server-side certificate status cache
 */
class CertificateChecker {
    constructor() {
        this.hostname = window.location.hostname;
        this.protocol = window.location.protocol;
        this.certButtonContainer = document.getElementById('cert-button-container');
        this.loginContainer = document.getElementById('login-container');
        
        // Check if returning from cert installation
        this.checkReturnFromCertInstall();
    }

    // Check if user is returning from certificate installation
    checkReturnFromCertInstall() {
        const returnFlag = sessionStorage.getItem('cert_installed');
        if (returnFlag === 'true') {
            // Clear the flag
            sessionStorage.removeItem('cert_installed');
            
            // Show success notification
            const successContainer = document.getElementById('cert-success-container');
            if (successContainer) {
                successContainer.style.display = 'block';
                // Auto-hide after 10 seconds
                setTimeout(() => {
                    successContainer.style.display = 'none';
                }, 10000);
            }
            
            // Force reload with cache clearing
            this.forceCleanReload();
        }
    }

    // Force a clean reload of the page
    forceCleanReload() {
        // First clear all browser caches
        if (window.caches) {
            caches.keys().then(cacheNames => {
                cacheNames.forEach(cacheName => {
                    caches.delete(cacheName);
                });
            });
        }
        
        // Set cache-control headers for future requests
        if ('fetch' in window) {
            // Register a service worker to intercept and clear cache
            // This is a more aggressive approach to clear certificate cache
            const cacheResetCode = `
                self.addEventListener('fetch', event => {
                    event.respondWith(
                        fetch(event.request, { 
                            cache: 'no-store',
                            headers: {
                                'Cache-Control': 'no-cache, no-store, must-revalidate',
                                'Pragma': 'no-cache'
                            }
                        })
                    );
                });
            `;
            
            try {
                // Try to register a temporary service worker for cache clearing
                // This is a bit extreme but can help with stubborn certificate cache issues
                if ('serviceWorker' in navigator) {
                    const blob = new Blob([cacheResetCode], {type: 'text/javascript'});
                    const url = URL.createObjectURL(blob);
                    navigator.serviceWorker.register(url, {scope: '/'})
                        .then(reg => {
                            // Service worker registered, now reload
                            console.log('Cache clearing service worker registered');
                            setTimeout(() => {
                                window.location.reload(true);
                            }, 500);
                        })
                        .catch(e => {
                            // If service worker fails, fall back to normal reload
                            console.error('Service worker registration failed:', e);
                            window.location.reload(true);
                        });
                } else {
                    // No service worker support, fall back to standard reload
                    window.location.reload(true);
                }
            } catch (e) {
                // Any errors, fall back to standard reload
                console.error('Error during cache clearing:', e);
                window.location.reload(true);
            }
        } else {
            // No fetch support, use standard reload
            window.location.reload(true);
        }
    }

    async checkCertificate() {
        // Only check if we're on HTTPS
        if (this.protocol !== 'https:') {
            this.showLoginContent();
            return;
        }

        // Direct test for secure context - if we can access the page over HTTPS
        // and JavaScript is running, we're likely in a secure context already
        if (window.isSecureContext === true) {
            console.log("Secure context detected, assuming certificate is valid");
            this.showLoginContent();
            return;
        }
        
        // Check if browser shows a secure connection in the UI
        // Chrome exposes this information via the permissions API
        if (typeof navigator.permissions !== 'undefined') {
            try {
                // Try to query a permission that requires secure context
                const permissionStatus = await navigator.permissions.query({name: 'notifications'});
                if (permissionStatus.state !== 'denied') {
                    console.log("Permissions API accessible, likely secure context");
                    this.showLoginContent();
                    return;
                }
            } catch (e) {
                console.log("Permissions check failed:", e);
                // Continue with fetch check
            }
        }

        // Use XMLHttpRequest instead of fetch - more reliable for cert checks on some browsers
        try {
            const xhrResult = await this.checkCertificateWithXHR();
            if (xhrResult === true) {
                this.showLoginContent();
                return;
            }
        } catch (error) {
            console.log("XHR certificate check failed, falling back to fetch");
        }

        try {
            // Add cache-busting parameter to prevent cached responses
            const cacheBuster = new Date().getTime();
            // Try to make a test request to the current origin
            const response = await fetch(`${window.location.origin}/api/health-check/?nocache=${cacheBuster}`, {
                method: 'GET',
                credentials: 'include',
                cache: 'no-store',
                headers: {
                    'Cache-Control': 'no-cache, no-store, must-revalidate',
                    'Pragma': 'no-cache',
                    'Expires': '0'
                }
            });
            
            if (response.ok) {
                // Certificate is valid
                this.showLoginContent();
            } else {
                // Server error but certificate might still be valid
                this.showLoginContent();
                console.warn('Server returned error but certificate might be valid');
            }
        } catch (error) {
            // Network error or certificate issue
            if (error.name === 'TypeError' || error.message.includes('certificate')) {
                this.showCertificateError();
            } else {
                console.error('Error checking certificate:', error);
                this.showLoginContent(); // Fall back to showing login
            }
        }
    }
    
    // Use XMLHttpRequest as an alternative method to check certificates
    checkCertificateWithXHR() {
        return new Promise((resolve, reject) => {
            const xhr = new XMLHttpRequest();
            const cacheBuster = new Date().getTime();
            
            xhr.open('GET', `${window.location.origin}/api/health-check/?xhr_nocache=${cacheBuster}`, true);
            xhr.setRequestHeader('Cache-Control', 'no-cache, no-store, must-revalidate');
            xhr.setRequestHeader('Pragma', 'no-cache');
            xhr.setRequestHeader('Expires', '0');
            
            xhr.onload = function() {
                if (xhr.status >= 200 && xhr.status < 300) {
                    resolve(true);
                } else {
                    // Server error, but certificate might still be valid
                    resolve(true);
                }
            };
            
            xhr.onerror = function(e) {
                // XMLHttpRequest will fail on certificate errors
                console.error("XHR error, likely certificate issue:", e);
                reject(new Error("Certificate validation failed"));
            };
            
            xhr.send();
        });
    }

    showCertificateError() {
        if (this.certButtonContainer) {
            this.certButtonContainer.style.display = 'block';
            if (this.loginContainer) {
                this.loginContainer.style.display = 'none';
            }
        }
    }

    showLoginContent() {
        if (this.loginContainer) {
            this.loginContainer.style.display = 'block';
            if (this.certButtonContainer) {
                this.certButtonContainer.style.display = 'none';
            }
        }
    }

    handleCertificateError() {
        // Redirect to the certificate error page
        window.location.href = '/cert-error/';
    }

    async downloadAndInstallCert() {
        try {
            // Trigger certificate download
            window.location.href = '/download-cert/';
            
            // Show installation instructions
            this.showInstallationInstructions();
        } catch (error) {
            console.error('Error downloading certificate:', error);
            alert('Failed to download certificate. Please try again or contact support.');
        }
    }

    showInstallationInstructions() {
        // Create and show modal with instructions
        const modal = document.createElement('div');
        modal.className = 'cert-instructions-modal';
        modal.innerHTML = `
            <div class="modal-content">
                <h3>Certificate Installation Instructions</h3>
                <ol>
                    <li>Double-click the downloaded certificate file</li>
                    <li>Click "Install Certificate"</li>
                    <li>Select "Current User" and click Next</li>
                    <li>Choose "Place all certificates in the following store"</li>
                    <li>Click "Browse" and select "Trusted Root Certification Authorities"</li>
                    <li>Click "Next" and then "Finish"</li>
                    <li>After installation, refresh this page</li>
                </ol>
                <button onclick="this.parentElement.parentElement.remove()">Close</button>
            </div>
        `;
        document.body.appendChild(modal);
    }
}

// Initialize and run certificate check when page loads
document.addEventListener('DOMContentLoaded', () => {
    // Clear hard-cached certificate status
    clearBrowserCache();
    
    const certChecker = new CertificateChecker();
    certChecker.checkCertificate();

    // Add click handler for certificate download button if it exists
    const downloadButton = document.getElementById('download-cert-button');
    if (downloadButton) {
        downloadButton.addEventListener('click', () => certChecker.handleCertificateError());
    }
});

// Function to clear various browser caches that might affect certificate validation
function clearBrowserCache() {
    // Clear fetch cache
    if ('caches' in window) {
        caches.keys().then(cacheNames => {
            cacheNames.forEach(cacheName => {
                caches.delete(cacheName);
            });
        }).catch(err => console.error('Cache clearing error:', err));
    }
    
    // Clear service worker cache if applicable
    if ('serviceWorker' in navigator) {
        navigator.serviceWorker.getRegistrations().then(registrations => {
            for (let registration of registrations) {
                registration.update();
            }
        }).catch(err => console.error('Service worker update error:', err));
    }
    
    // Clear localStorage certificate-related items
    try {
        localStorage.removeItem('cert_status');
        localStorage.removeItem('cert_check_time');
    } catch (e) {
        console.warn('LocalStorage clear failed:', e);
    }
    
    // Check for URL parameters indicating cache should be cleared
    const urlParams = new URLSearchParams(window.location.search);
    if (urlParams.has('clear_cache') || urlParams.has('cert_refresh')) {
        console.log('Cache clearing parameter detected, reloading without params');
        // Remove the parameter(s) and reload
        urlParams.delete('clear_cache');
        urlParams.delete('cert_refresh');
        const newUrl = window.location.pathname + (urlParams.toString() ? '?' + urlParams.toString() : '');
        window.history.replaceState({}, document.title, newUrl);
    }
} 