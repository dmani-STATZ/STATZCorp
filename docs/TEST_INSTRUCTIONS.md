# Testing the Change Indicators - Quick Guide

## What to Look For

### 1. When the Page Loads (First 3 seconds)
You should see a **green notification** in the top-right corner that says:
```
✅ Change Tracking Active
```

**If you see this:** JavaScript is loaded and working! ✅
**If you DON'T see this:** JavaScript is not loading properly ❌

---

### 2. Open Browser Console (Press F12)
You should see these messages in GREEN:
```
✅ supplier_edit.js loaded successfully
[SupplierEdit] 🚀 Initializing supplier edit form...
[SupplierEdit] ✅ Form found
[SupplierEdit] Initializing X toggle controls...
[SupplierEdit] ✅ Initialization complete.
[SupplierEdit] 📊 Tracking X form fields
```

**If you see RED errors instead:**
- Copy the error message and send it to me
- This will tell us exactly what's wrong

---

### 3. Test a Field Change

#### Try the Name Field:
1. Click in the **Name** field (first field at the top)
2. Add a letter or space
3. Click outside the field

#### What Should Happen:
- **Console**: You'll see: `[SupplierEdit] Field changed via input: name (old -> new)`
- **Visual**: An **amber/orange pulsing bar** appears on the LEFT edge of the field
- **Border**: The input field gets an **amber border**
- **Save Button**: A small badge appears showing **(1)** for 1 changed field

#### Try the Toggles (Probation, PPI, etc.):
1. Click **On** or **Off** on any toggle
2. The toggle should change color

#### What Should Happen:
- **Console**: `[SupplierEdit] Toggle probation changed: false -> true`
- **Visual**: A **glowing ring** appears around the toggle control
- **Save Button**: Badge count increases

---

## Quick Diagnostics

### Problem: Nothing happens, no green notification
**Solution:**
1. Hard refresh: **Ctrl + Shift + R** (Chrome/Edge) or **Ctrl + F5**
2. Check if you're in Django DEBUG mode
3. Check Network tab in DevTools for 404 errors

### Problem: Green notification appears, but no change indicators
**Check in Console, paste this:**
```javascript
// Test the CSS
const testDiv = document.createElement('div');
testDiv.className = 'change-indicator';
document.body.appendChild(testDiv);
```

If you see a thin orange bar appear, CSS is working.

### Problem: Console shows errors
**Send me the exact error message** - I'll fix it immediately.

---

## What to Tell Me

Please report back with:
1. ✅ or ❌ for "Green notification appeared"
2. ✅ or ❌ for "Console shows initialization messages"
3. ✅ or ❌ for "Amber bar appears when changing name field"
4. ✅ or ❌ for "Toggle controls show ring highlight"
5. Any **error messages** from the console (copy/paste)

This will help me quickly identify and fix the issue!

