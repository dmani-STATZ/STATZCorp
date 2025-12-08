# Quick Fix: Clear Browser Cache Completely

## The Problem
Your browser has cached old versions of the JavaScript file, causing duplicate variable declarations.

## The Solution (2 minutes)

### Method 1: Chrome DevTools (Easiest)
1. **Right-click** on the page
2. Click **"Inspect"** (or press F12)
3. **Right-click on the Refresh button** (next to the address bar)
4. Select **"Empty Cache and Hard Reload"**
5. Close DevTools
6. Refresh the page one more time

### Method 2: Manual Cache Clear
1. Press **Ctrl + Shift + Delete** (or Cmd + Shift + Delete on Mac)
2. Select **"All time"** for time range
3. Check **"Cached images and files"**
4. Click **"Clear data"**
5. Close the dialog
6. Hard refresh: **Ctrl + Shift + R**

### Method 3: Incognito/Private Window (Quick Test)
1. Press **Ctrl + Shift + N** (Chrome) or **Ctrl + Shift + P** (Firefox/Edge)
2. Navigate to: `http://127.0.0.1:8000/suppliers/1/edit/`
3. Test if the change indicators work there

If it works in Incognito, it's definitely a cache issue!

## After Clearing Cache

You should see:
- ✅ NO red errors in Console
- ✅ Green "Change Tracking Active" notification
- ✅ Console shows: `✅ supplier_edit.js loaded successfully`
- ✅ When you change a field, amber indicators appear

## If Still Not Working

Try adding this to force a new version:
- I'll update the cache-busting version number


