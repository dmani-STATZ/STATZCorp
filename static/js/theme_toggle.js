// theme_toggle.js

document.addEventListener('DOMContentLoaded', function() {
    const btn = document.getElementById('theme-toggle');
    const icon = document.getElementById('theme-toggle-icon');
    console.log('Theme toggle initialized:', { btn: !!btn, icon: !!icon });
    
    if (!btn) return;
    
    // Check initial theme
    const isDarkMode = document.body.classList.contains('dark');
    console.log('Initial dark mode:', isDarkMode);
    
    btn.addEventListener('click', function() {
        console.log('Theme toggle clicked');
        const isDark = document.body.classList.contains('dark');
        const newTheme = isDark ? 'light' : 'dark';
        console.log('Switching to:', newTheme);
        
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
            document.body.classList.toggle('dark');
            console.log('Dark mode after toggle:', document.body.classList.contains('dark'));
        }).catch(error => {
            console.error('Error saving theme:', error);
        });
    });
});

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