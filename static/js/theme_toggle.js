/**
 * STATZ Corporation - Theme Toggle System
 *
 * This JavaScript file handles the theme toggle functionality between light and dark modes.
 * It works in conjunction with the light-mode.css and dark-mode.css files to provide a
 * consistent theming experience.
 * 
 * The main components:
 * 1. Event listener for the theme toggle button
 * 2. Logic to switch between light and dark modes
 * 3. AJAX to save user preference to the database
 * 4. Icon switching between sun (light mode) and moon (dark mode)
 */

document.addEventListener('DOMContentLoaded', function() {
    const btn = document.getElementById('theme-toggle');
    const icon = document.getElementById('theme-toggle-icon');
    console.log('Theme toggle initialized:', { btn: !!btn, icon: !!icon });
    
    if (!btn) return;
    
    // Check initial theme
    const isDarkMode = document.body.classList.contains('dark');
    console.log('Initial dark mode:', isDarkMode);
    
    // Force apply correct theme immediately to avoid flicker
    applyThemeStyles(isDarkMode);
    
    // Force reload CSS files on initial page load
    updateCssVersions();
    
    btn.addEventListener('click', function() {
        console.log('Theme toggle clicked');
        const isDark = document.body.classList.contains('dark');
        const newTheme = isDark ? 'light' : 'dark';
        console.log('Switching to:', newTheme);
        
        // Save user preference via AJAX
        fetch('/users/settings/ajax/save/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCookie('csrftoken'),
            },
            body: JSON.stringify({
                user_id: window.CURRENT_USER_ID,
                setting_name: 'theme',
                setting_value: newTheme,
                setting_type: 'string'
            })
        }).then(response => {
            console.log('Theme save response:', response.ok);
            if (response.ok) {
                // Toggle the theme class on the body
                document.body.classList.toggle('dark');
                const newIsDark = document.body.classList.contains('dark');
                console.log('Dark mode after toggle:', newIsDark);
                
                // Apply immediate styling
                applyThemeStyles(newIsDark);
                
                // Update the icon based on new theme
                updateThemeIcon(newIsDark);
                
                // Force reload of CSS files by updating their version
                updateCssVersions();
            } else {
                console.error('Failed to save theme preference');
            }
        }).catch(error => {
            console.error('Error saving theme:', error);
        });
    });
    
    /**
     * Updates the theme toggle icon based on current theme
     * @param {boolean} isDark - Whether the current theme is dark
     */
    function updateThemeIcon(isDark) {
        // Clear the current icon content
        while (icon.firstChild) {
            icon.removeChild(icon.firstChild);
        }
        
        // Create the appropriate SVG path based on theme
        const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
        path.setAttribute("stroke-linecap", "round");
        path.setAttribute("stroke-linejoin", "round");
        path.setAttribute("stroke-width", "2");
        
        if (isDark) {
            // Moon icon for dark mode
            path.setAttribute("d", "M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z");
        } else {
            // Sun icon for light mode
            path.setAttribute("d", "M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z");
        }
        
        icon.appendChild(path);
    }
});

/**
 * Gets the value of a cookie by name
 * @param {string} name - The name of the cookie to retrieve
 * @return {string|null} The cookie value or null if not found
 */
function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
        const cookies = document.cookie.split(';');
        for (let i = 0; i < cookies.length; i++) {
            const cookie = cookies[i].trim();
            if (cookie.substring(0, name.length + 1) === (name + '=')) {
                cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                break;
            }
        }
    }
    return cookieValue;
}

/**
 * Updates the version parameter in CSS file URLs to force a refresh
 */
function updateCssVersions() {
    const cssLinks = document.querySelectorAll('link[rel="stylesheet"]');
    const newVersion = Date.now(); // Use timestamp as version
    
    cssLinks.forEach(link => {
        const href = link.getAttribute('href');
        if (href && (href.includes('base.css') || href.includes('light-mode.css') || href.includes('dark-mode.css'))) {
            // Remove any existing version parameter
            const baseUrl = href.split('?')[0];
            link.setAttribute('href', `${baseUrl}?v=${newVersion}`);
        }
    });
}

/**
 * Force applies the current theme styles to relevant elements
 * @param {boolean} isDark - Whether to apply dark mode
 */
function applyThemeStyles(isDark) {
    // Get key elements that need immediate styling
    const header = document.getElementById('header');
    const sidebar = document.getElementById('sidebar');
    const content = document.getElementById('content');
    
    if (isDark) {
        // Apply dark mode styles
        document.body.style.backgroundColor = '#1f2937'; // dark gray
        document.body.style.color = '#f9fafb'; // white
        
        if (header) header.style.backgroundColor = '#004eb3'; // Keep blue header
        if (sidebar) sidebar.style.backgroundColor = '#e00000'; // Keep red sidebar
        if (content) content.style.backgroundColor = '#1f2937'; // dark gray
    } else {
        // Apply light mode styles
        document.body.style.backgroundColor = '#f9fafb'; // light gray
        document.body.style.color = '#111827'; // dark gray
        
        if (header) header.style.backgroundColor = '#004eb3'; // Keep blue header
        if (sidebar) sidebar.style.backgroundColor = '#e00000'; // Keep red sidebar
        if (content) content.style.backgroundColor = '#f9fafb'; // light gray
    }
} 