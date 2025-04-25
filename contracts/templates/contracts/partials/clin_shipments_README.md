# CLIN Shipments Component

A reusable Django template component for displaying and managing CLIN shipments in both form and detail views.

## Features

- Dual mode support (form/detail)
- Real-time shipment quantity calculations
- AJAX-based CRUD operations
- Visual feedback for unsaved changes
- Show/Hide functionality
- Responsive design with Tailwind CSS
- Toast notifications for actions

## Prerequisites

- Django 3.2+
- Tailwind CSS
- CSRF token enabled
- jQuery (optional, for toast notifications)

## Installation

1. Copy the component files to your project:
```bash
contracts/
├── templates/
│   └── contracts/
│       └── partials/
│           └── clin_shipments.html
└── static/
    └── contracts/
        └── js/
            └── clin_shipments.js
```

2. Add the JavaScript to your static files:
```python
# settings.py
STATICFILES_DIRS = [
    ...
    os.path.join(BASE_DIR, 'contracts/static'),
]
```

## Basic Usage

### 1. Include Required Assets

Add these to your base template or specific page:

```html
{% load static %}

<!-- In the head section -->
<link href="https://cdn.jsdelivr.net/npm/toastify-js/src/toastify.min.css" rel="stylesheet"> <!-- Optional for notifications -->

<!-- Before closing body tag -->
<script src="https://cdn.jsdelivr.net/npm/toastify-js"></script> <!-- Optional for notifications -->
<script src="{% static 'contracts/js/clin_shipments.js' %}"></script>
```

### 2. Include the Component

For detail view (read-only):
```html
{% include "contracts/partials/clin_shipments.html" with mode="detail" clin=clin %}
```

For form view (editable):
```html
{% include "contracts/partials/clin_shipments.html" with mode="form" clin=form.instance %}
```

## Required Context Variables

| Variable | Type | Description |
|----------|------|-------------|
| mode | string | Either "form" or "detail" |
| clin | Clin | CLIN object with shipments relationship |

## API Endpoints Required

The component expects these API endpoints to be available:

```python
# urls.py
urlpatterns = [
    path('api/shipments/create/', views.create_shipment, name='create_shipment'),
    path('api/shipments/update/<int:shipment_id>/', views.update_shipment, name='update_shipment'),
    path('api/shipments/delete/<int:shipment_id>/', views.delete_shipment, name='delete_shipment'),
]
```

Expected API Response Format:
```json
{
    "success": true/false,
    "shipment_id": 123,  // For create operations
    "error": "Error message if success is false"
}
```

## Integration Examples

### 1. Basic Detail Page
```html
{% extends "base.html" %}

{% block content %}
<div class="container mx-auto px-4 py-8">
    <h1>CLIN Details: {{ clin.item_number }}</h1>
    
    <!-- CLIN Shipments Component -->
    {% include "contracts/partials/clin_shipments.html" with mode="detail" clin=clin %}
</div>
{% endblock %}
```

### 2. Form Page with Validation
```html
{% extends "base.html" %}

{% block content %}
<form method="post">
    {% csrf_token %}
    
    <!-- Other form fields -->
    
    {% include "contracts/partials/clin_shipments.html" with mode="form" clin=form.instance %}
    
    <button type="submit">Save CLIN</button>
</form>
{% endblock %}
```

### 3. Dynamic Loading via AJAX
```javascript
async function loadClinShipments(clinId) {
    const response = await fetch(`/contracts/shipments/${clinId}/`);
    const html = await response.text();
    document.getElementById('shipments-container').innerHTML = html;
    ClinShipments.init(); // Reinitialize the component
}
```

## Customization

### 1. Styling
The component uses Tailwind CSS classes. Override these classes in your CSS:

```css
/* Your CSS */
.section-header {
    /* Your custom styles */
}

.shipment-row {
    /* Your custom styles */
}
```

### 2. Messages
Customize the message display by modifying the `showMessage` function:

```javascript
// Your custom message handler
ClinShipments.showMessage = function(message, type) {
    // Your custom notification logic
};
```

### 3. Validation
Add custom validation by extending the `saveShipment` method:

```javascript
const originalSaveShipment = ClinShipments.saveShipment;
ClinShipments.saveShipment = async function(button) {
    // Your custom validation
    if (!isValid) {
        this.showMessage('Validation failed', 'error');
        return;
    }
    return originalSaveShipment.call(this, button);
};
```

## Events

The component triggers these events:

```javascript
// Listen for shipment changes
document.addEventListener('shipmentUpdated', (e) => {
    console.log('Shipment updated:', e.detail);
});

document.addEventListener('shipmentDeleted', (e) => {
    console.log('Shipment deleted:', e.detail);
});
```

## Troubleshooting

1. **Shipments not saving:**
   - Check CSRF token is present
   - Verify API endpoints are correctly configured
   - Check browser console for errors

2. **Totals not updating:**
   - Ensure shipment quantities are valid numbers
   - Check if totalShipQty element exists

3. **Styling issues:**
   - Verify Tailwind CSS is properly loaded
   - Check for CSS conflicts in your main stylesheet

## Best Practices

1. Always include CSRF token in forms
2. Use proper error handling in API endpoints
3. Validate data on both client and server side
4. Keep clin.shipments relationship eager-loaded
5. Use appropriate caching for read-only views

## Contributing

Feel free to submit issues and enhancement requests!

## License

This component is MIT licensed. 