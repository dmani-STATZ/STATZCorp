# Contract Splits Component

A reusable Django template component for displaying and managing contract splits in both form and detail views.

## Features

- Dual mode support (form/detail)
- Real-time split calculations
- AJAX-based CRUD operations
- Visual feedback for unsaved changes
- Show/Hide functionality
- Responsive design with Tailwind CSS
- Automatic validation against plan_gross
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
│           └── contract_splits.html
└── static/
    └── contracts/
        └── js/
            └── contract_splits.js
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
<script src="{% static 'contracts/js/contract_splits.js' %}"></script>
```

### 2. Include the Component

For detail view (read-only):
```html
{% include "contracts/partials/contract_splits.html" with mode="detail" contract=contract %}
```

For form view (editable):
```html
{% include "contracts/partials/contract_splits.html" with mode="form" contract=form.instance %}
```

## Required Context Variables

| Variable | Type | Description |
|----------|------|-------------|
| mode | string | Either "form" or "detail" |
| contract | Contract | Contract object with splits relationship |

## API Endpoints Required

The component expects these API endpoints to be available:

```python
# urls.py
urlpatterns = [
    path('api/splits/create/', views.create_split, name='create_split'),
    path('api/splits/update/<int:split_id>/', views.update_split, name='update_split'),
    path('api/splits/delete/<int:split_id>/', views.delete_split, name='delete_split'),
]
```

Expected API Response Format:
```json
{
    "success": true/false,
    "split_id": 123,  // For create operations
    "error": "Error message if success is false"
}
```

## Integration Examples

### 1. Basic Detail Page
```html
{% extends "base.html" %}

{% block content %}
<div class="container mx-auto px-4 py-8">
    <h1>Contract Details: {{ contract.number }}</h1>
    
    <!-- Contract Splits Component -->
    {% include "contracts/partials/contract_splits.html" with  mode="detail" contract=contract %}
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
    
    {% include "contracts/partials/contract_splits.html" with mode="form" contract=form.instance %}
    
    <button type="submit">Save Contract</button>
</form>
{% endblock %}
```

### 3. Dynamic Loading via AJAX
```javascript
async function loadContractSplits(contractId) {
    const response = await fetch(`/contracts/splits/${contractId}/`);
    const html = await response.text();
    document.getElementById('splits-container').innerHTML = html;
    ContractSplits.init(); // Reinitialize the component
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

.split-row {
    /* Your custom styles */
}
```

### 2. Messages
Customize the message display by modifying the `showMessage` function:

```javascript
// Your custom message handler
ContractSplits.showMessage = function(message, type) {
    // Your custom notification logic
};
```

### 3. Validation
Add custom validation by extending the `saveSplit` method:

```javascript
const originalSaveSplit = ContractSplits.saveSplit;
ContractSplits.saveSplit = async function(button) {
    // Your custom validation
    if (!isValid) {
        this.showMessage('Validation failed', 'error');
        return;
    }
    return originalSaveSplit.call(this, button);
};
```

## Events

The component triggers these events:

```javascript
// Listen for split changes
document.addEventListener('splitUpdated', (e) => {
    console.log('Split updated:', e.detail);
});

document.addEventListener('splitDeleted', (e) => {
    console.log('Split deleted:', e.detail);
});
```

## Troubleshooting

1. **Splits not saving:**
   - Check CSRF token is present
   - Verify API endpoints are correctly configured
   - Check browser console for errors

2. **Totals not updating:**
   - Ensure split values are valid numbers
   - Check if totalSplitValue/totalSplitPaid elements exist

3. **Styling issues:**
   - Verify Tailwind CSS is properly loaded
   - Check for CSS conflicts in your main stylesheet

## Best Practices

1. Always include CSRF token in forms
2. Use proper error handling in API endpoints
3. Validate data on both client and server side
4. Keep contract.splits relationship eager-loaded
5. Use appropriate caching for read-only views

## Contributing

Feel free to submit issues and enhancement requests!

## License

This component is MIT licensed. 