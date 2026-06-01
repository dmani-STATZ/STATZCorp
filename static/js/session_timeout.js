(function() {
  // Configuration
  const MAX_AGE_SECONDS = window.STATZ_SESSION_MAX_AGE || 3600;
  const WARN_BEFORE_SECONDS = 300;
  const POLL_PAUSE_SECONDS = 900;
  const KEEPALIVE_URL = window.STATZ_KEEPALIVE_URL || '/users/session/keep-alive/';
  const CSRF_TOKEN = window.STATZ_CSRF_TOKEN || '';

  let internalLastActivityMs = Date.now();
  let countdownInterval = null;
  let pollingPaused = false;

  // Initialize from localStorage
  const stored = localStorage.getItem('statz_last_activity');
  if (stored) {
    const parsed = Date.parse(stored);
    if (!isNaN(parsed)) {
      internalLastActivityMs = parsed;
    }
  } else {
    localStorage.setItem('statz_last_activity', new Date().toISOString());
  }

  // Cross-tab sync
  window.addEventListener('storage', (event) => {
    if (event.key === 'statz_last_activity' && event.newValue) {
      const parsed = Date.parse(event.newValue);
      if (!isNaN(parsed)) {
        internalLastActivityMs = parsed;
      }
    }
  });

  // Throttled activity event listeners
  let lastActivityEventTime = 0;
  function handleActivity() {
    const now = Date.now();
    if (now - lastActivityEventTime >= 5000) {
      lastActivityEventTime = now;
      const isoString = new Date().toISOString();
      localStorage.setItem('statz_last_activity', isoString);
      internalLastActivityMs = now;
    }
  }

  ['mousemove', 'keydown', 'click', 'scroll', 'touchstart'].forEach(eventName => {
    window.addEventListener(eventName, handleActivity, { passive: true });
  });

  // Format MM:SS helper
  function formatTime(seconds) {
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    const minsStr = mins < 10 ? '0' + mins : mins;
    const secsStr = secs < 10 ? '0' + secs : secs;
    return minsStr + ':' + secsStr;
  }

  // Warning Modal management
  function showWarningModal(secondsRemaining) {
    let modal = document.getElementById('session-warning-modal');
    if (!modal) {
      modal = document.createElement('div');
      modal.id = 'session-warning-modal';
      modal.setAttribute('data-visible', 'true');
      modal.style.display = 'block';
      modal.innerHTML = `
        <div id="session-warning-modal-inner">
          <h2 class="session-timeout-title">Your session is about to expire</h2>
          <p class="session-timeout-body mb-2">You will be signed out in</p>
          <span id="session-countdown-display"></span>
          <p class="session-timeout-body mt-2">Any unsaved work will be lost.</p>
          <div class="session-timeout-buttons">
            <button id="session-stay-btn" class="btn btn-success" type="button">Stay Connected</button>
            <button id="session-signout-btn" class="btn btn-outline-secondary" type="button">Sign Out</button>
          </div>
        </div>
      `;
      document.body.appendChild(modal);

      const stayBtn = document.getElementById('session-stay-btn');
      if (stayBtn) {
        stayBtn.addEventListener('click', stayConnected);
      }
      const signoutBtn = document.getElementById('session-signout-btn');
      if (signoutBtn) {
        signoutBtn.addEventListener('click', signOut);
      }
    } else {
      modal.setAttribute('data-visible', 'true');
      modal.style.display = 'block';
    }

    const display = document.getElementById('session-countdown-display');
    if (display) {
      display.textContent = formatTime(secondsRemaining);
    }

    if (!countdownInterval) {
      countdownInterval = setInterval(() => {
        const storedStr = localStorage.getItem('statz_last_activity');
        let lastActivityMs = internalLastActivityMs;
        if (storedStr) {
          const parsed = Date.parse(storedStr);
          if (!isNaN(parsed)) {
            lastActivityMs = parsed;
          }
        }
        const secsInactive = (Date.now() - lastActivityMs) / 1000;
        const timeUntilExp = MAX_AGE_SECONDS - secsInactive;

        if (timeUntilExp <= 0) {
          showExpiredOverlay();
        } else {
          const displayEl = document.getElementById('session-countdown-display');
          if (displayEl) {
            displayEl.textContent = formatTime(timeUntilExp);
          }
        }
      }, 1000);
    }
  }

  function hideWarningModal() {
    const modal = document.getElementById('session-warning-modal');
    if (modal) {
      modal.setAttribute('data-visible', 'false');
      modal.style.display = 'none';
    }
    if (countdownInterval) {
      clearInterval(countdownInterval);
      countdownInterval = null;
    }
  }

  // Expired Overlay management
  function showExpiredOverlay() {
    hideWarningModal();

    if (mainInterval) {
      clearInterval(mainInterval);
      mainInterval = null;
    }

    stopPolling();

    let overlay = document.getElementById('session-expired-overlay');
    if (!overlay) {
      overlay = document.createElement('div');
      overlay.id = 'session-expired-overlay';
      overlay.setAttribute('data-visible', 'true');
      overlay.style.display = 'block';
      overlay.innerHTML = `
        <div id="session-expired-inner">
          <i class="bi bi-lock-fill session-timeout-icon"></i>
          <h2 class="session-timeout-title">Your session has expired</h2>
          <p class="session-timeout-body">To protect your work, please log back in. If you have unsaved changes in this tab, log in using a new tab  then return here to save.</p>
          <div class="session-timeout-buttons">
            <a id="session-login-new-tab" class="btn btn-primary btn-lg" href="" target="_blank" rel="noopener noreferrer">Log In in a New Tab</a>
            <button id="session-reload-btn" class="btn btn-outline-secondary" type="button">Reload Page</button>
          </div>
        </div>
      `;
      document.body.appendChild(overlay);

      const loginLink = document.getElementById('session-login-new-tab');
      if (loginLink) {
        loginLink.href = window.STATZ_LOGIN_URL || '';
      }

      const reloadBtn = document.getElementById('session-reload-btn');
      if (reloadBtn) {
        reloadBtn.addEventListener('click', () => {
          window.location.reload();
        });
      }
    } else {
      overlay.setAttribute('data-visible', 'true');
      overlay.style.display = 'block';
    }
  }

  // Keep-alive request
  function stayConnected() {
    fetch(KEEPALIVE_URL, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded',
        'X-CSRFToken': CSRF_TOKEN
      },
      body: 'csrfmiddlewaretoken=' + encodeURIComponent(CSRF_TOKEN)
    })
    .then(response => {
      if (response.ok && response.status === 200) {
        const nowStr = new Date().toISOString();
        localStorage.setItem('statz_last_activity', nowStr);
        internalLastActivityMs = Date.now();
        hideWarningModal();
      } else {
        showExpiredOverlay();
      }
    })
    .catch(() => {
      showExpiredOverlay();
    });
  }

  // Sign out helper
  function signOut() {
    const form = document.createElement('form');
    form.method = 'POST';
    form.action = window.STATZ_LOGOUT_URL || '';
    form.style.display = 'none';

    const csrfInput = document.createElement('input');
    csrfInput.type = 'hidden';
    csrfInput.name = 'csrfmiddlewaretoken';
    csrfInput.value = CSRF_TOKEN;
    form.appendChild(csrfInput);

    document.body.appendChild(form);
    form.submit();
  }

  // Intercepting fetch for expired-session detection
  const _origFetch = window.fetch;
  window.fetch = function(...args) {
    return _origFetch.apply(this, args).then(response => {
      if (response.url && response.url.includes('/users/login/') && response.redirected) {
        showExpiredOverlay();
      }
      return response;
    });
  };

  // Stop polling helper
  function stopPolling() {
    pollingPaused = true;
  }

  // Public API
  window.sessionTimeout = {
    isUserActive: function() {
      if (pollingPaused) {
        return false;
      }
      const storedStr = localStorage.getItem('statz_last_activity');
      let lastActivityMs = internalLastActivityMs;
      if (storedStr) {
        const parsed = Date.parse(storedStr);
        if (!isNaN(parsed)) {
          lastActivityMs = parsed;
        }
      }
      const secsInactive = (Date.now() - lastActivityMs) / 1000;
      return secsInactive < POLL_PAUSE_SECONDS;
    },
    stopPolling: stopPolling
  };

  // Main checking loop running every 10 seconds
  let mainInterval = setInterval(() => {
    const storedStr = localStorage.getItem('statz_last_activity');
    let lastActivityMs = internalLastActivityMs;
    if (storedStr) {
      const parsed = Date.parse(storedStr);
      if (!isNaN(parsed)) {
        lastActivityMs = parsed;
      }
    }
    const secsInactive = (Date.now() - lastActivityMs) / 1000;
    const timeUntilExp = MAX_AGE_SECONDS - secsInactive;

    if (secsInactive >= MAX_AGE_SECONDS) {
      showExpiredOverlay();
    } else if (timeUntilExp <= WARN_BEFORE_SECONDS) {
      showWarningModal(timeUntilExp);
    } else {
      // Handles the case where another tab renewed the session
      const modal = document.getElementById('session-warning-modal');
      if (modal && modal.getAttribute('data-visible') === 'true') {
        hideWarningModal();
      }
    }
  }, 10000);
})();
