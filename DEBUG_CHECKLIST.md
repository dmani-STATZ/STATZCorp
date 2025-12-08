# Debugging Checklist for Change Indicators

## Step 1: Open Browser Console
1. Press **F12** to open Developer Tools
2. Click on the **Console** tab
3. Refresh the page (Ctrl+R or F5)

### What you should see in console:
```
[SupplierEdit] Initializing supplier edit form...
[SupplierEdit] Found X form elements
[SupplierEdit] Checkbox id_probation (probation): false
[SupplierEdit] Initializing X toggle controls...
[SupplierEdit] Initialization complete.
```

### If you DON'T see these messages:
- ❌ JavaScript file is not loading
- Solution: Check Network tab, look for 404 errors on supplier_edit.js

## Step 2: Check for JavaScript Errors
Look for any RED error messages in the console.

Common errors:
- "Uncaught ReferenceError" - missing variable
- "Uncaught SyntaxError" - JavaScript syntax error
- "Failed to load resource" - file not found

## Step 3: Test a Simple Field Change
1. Find the **Name** field at the top
2. Change the value (add a space or letter)
3. Tab out of the field or click elsewhere

### What you should see:
- In console: `[SupplierEdit] Field changed via input: name (old_value -> new_value)`
- Visually: Nothing yet (we'll check in Step 4)

## Step 4: Check CSS is Loaded
1. In Developer Tools, click on **Elements** tab
2. Find the `<head>` section
3. Look for: `<link rel="stylesheet" href="/static/css/base.css">`
4. Click on it - should show the CSS file with `.change-indicator` styles

### If CSS is not loaded:
- Run `python manage.py collectstatic --noinput`
- Hard refresh: Ctrl+Shift+R

## Step 5: Manual Test of Visual Indicator
1. In Console tab, paste this command:
```javascript
const testDiv = document.createElement('div');
testDiv.className = 'change-indicator';
testDiv.style.cssText = 'position: absolute; left: 0; top: 0; width: 4px; height: 50px; background: #f59e0b;';
document.body.appendChild(testDiv);
```
2. Press Enter

### What you should see:
- A small orange/amber bar appear on the left side of the page
- If you DON'T see this: CSS is not loaded properly

## Step 6: Check Element IDs
1. In Console, paste:
```javascript
const form = document.querySelector('form');
const inputs = form.querySelectorAll('input, select, textarea');
console.log('Total inputs:', inputs.length);
inputs.forEach(el => {
    if (el.id && el.name && !el.name.includes('csrf')) {
        console.log(`${el.name}: id="${el.id}" type="${el.type}"`);
    }
});
```

This will list all form fields with their IDs.

## Step 7: Force a Change Indicator
1. In Console, paste:
```javascript
const nameField = document.getElementById('id_name');
if (nameField) {
    console.log('Name field found:', nameField);
    nameField.value = nameField.value + ' TEST';
    nameField.dispatchEvent(new Event('input', { bubbles: true }));
} else {
    console.log('ERROR: Name field not found!');
}
```

This will programmatically change the name field and trigger the change detection.

## What to Report Back

Please tell me:
1. **Console Messages**: What do you see in Step 1?
2. **Errors**: Any red error messages?
3. **Step 7 Result**: Did the indicator appear after running Step 7?
4. **Browser**: Which browser are you using? (Chrome, Firefox, Edge, etc.)

