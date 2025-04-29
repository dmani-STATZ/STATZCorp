// Certificate checker and installer
class CertificateChecker {
    constructor() {
        this.hostname = window.location.hostname;
        this.protocol = window.location.protocol;
        this.certButtonContainer = document.getElementById('cert-button-container');
        this.loginContainer = document.getElementById('login-container');
    }

    async checkCertificate() {
        // Only check if we're on HTTPS
        if (this.protocol !== 'https:') {
            this.showLoginContent();
            return;
        }

        try {
            // Try to make a test request to the current origin
            const response = await fetch(window.location.origin + '/api/health-check/', {
                method: 'GET',
                credentials: 'include'
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
        downloadButton.addEventListener('click', () => certChecker.downloadAndInstallCert());
    }
}); 