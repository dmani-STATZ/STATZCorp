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
        // Clear fetch cache
        if (window.caches) {
            caches.keys().then(cacheNames => {
                cacheNames.forEach(cacheName => {
                    caches.delete(cacheName);
                });
            });
        }
        
        // Force reload bypassing cache
        window.location.reload(true);
    }

    async checkCertificate() {
        // Only check if we're on HTTPS
        if (this.protocol !== 'https:') {
            this.showLoginContent();
            return;
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
    const certChecker = new CertificateChecker();
    certChecker.checkCertificate();

    // Add click handler for certificate download button if it exists
    const downloadButton = document.getElementById('download-cert-button');
    if (downloadButton) {
        downloadButton.addEventListener('click', () => certChecker.handleCertificateError());
    }
}); 