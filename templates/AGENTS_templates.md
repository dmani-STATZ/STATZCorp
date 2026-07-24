# AGENTS.md — `templates` Directory

## Script Loading Order in base_template.html
jQuery 3.6.0, jQuery UI 1.12.1, and Bootstrap 5.3.3 bundle are all
loaded in <head> as synchronous blocking scripts. They are available
on window (window.jQuery / window.$ / window.bootstrap) by the time
any script in {% block content %} or {% block extra_js %} executes.
Do NOT move these to the bottom of <body>. Any inline script in a
content block may safely reference bootstrap.Modal, bootstrap.Tooltip,
etc. without DOMContentLoaded guards for initialization.
