# Build Number Solution for Production

## Problem
The build number was showing as "unknown" on the production server because the Git repository is not available in Azure App Service deployments.

## Solution
Implemented a comprehensive version detection system with multiple fallback methods:

### 1. Enhanced Version Detection (`STATZWeb/version_utils.py`)
- **Git Detection**: Primary method using Git commands (works in development)
- **Environment Variables**: Fallback for production deployments
- **File-based Tracking**: Persistent version info stored in `version_info.json`
- **Deployment Timestamps**: Azure App Service deployment time tracking
- **Auto-generated Build Numbers**: Timestamp-based build numbers when needed

### 2. Environment Variable Support
Set these in Azure App Service Application Settings:
```bash
BUILD_COMMIT_HASH=abc123def456...
BUILD_SHORT_HASH=abc1234
BUILD_BRANCH=main
BUILD_TAG=v1.2.3
BUILD_DATE=2024-01-15
BUILD_NUMBER=build-123
WEBSITE_DEPLOYMENT_ID=deployment-456
```

### 3. Management Commands
- `python manage.py set_build_info --auto`: Auto-generate build info
- `python manage.py set_build_info --build-number "v1.2.3" --commit-hash "abc123"`: Manual setup

### 4. Deployment Scripts
- `scripts/set_production_version.py`: Standalone script for deployment
- `scripts/azure-deployment-version.yml`: Azure DevOps pipeline step

## Implementation Details

### Version Detection Priority
1. **Git Information** (if available)
2. **Environment Variables** (production deployments)
3. **File-based Version** (persistent storage)
4. **Deployment Timestamps** (Azure App Service)
5. **Auto-generated** (timestamp-based)

### Build Number Generation
- Uses `WEBSITE_DEPLOYMENT_ID` if available
- Falls back to Git short hash
- Generates timestamp-based build number as last resort

### Template Updates
- **Header Bar**: Shows build number below version
- **Landing Page**: Displays build number in version section
- **System Test**: Shows build number in header

## Quick Setup for Production

### Method 1: Azure Portal
1. Go to Azure App Service → Configuration → Application Settings
2. Add these variables:
   ```
   BUILD_NUMBER=build-20240115-1430
   BUILD_DATE=2024-01-15
   BUILD_BRANCH=main
   ```
3. Restart the App Service

### Method 2: Azure CLI
```bash
az webapp config appsettings set \
  --name your-app-name \
  --resource-group your-rg \
  --settings \
  BUILD_NUMBER="build-20240115-1430" \
  BUILD_DATE="2024-01-15" \
  BUILD_BRANCH="main"
```

### Method 3: Management Command
```bash
# SSH into Azure App Service
az webapp ssh --name your-app-name --resource-group your-rg

# Run the command
python manage.py set_build_info --auto
```

## Testing

### Local Testing
```bash
# Test version detection
python manage.py show_version

# Test build info setting
python manage.py set_build_info --build-number "test-build-123"
```

### Production Testing
1. Visit the system test page: `https://your-app.azurewebsites.us/system-test/`
2. Check the header bar for build number
3. Verify landing page shows build information

## Troubleshooting

### Build Number Still Shows "unknown"
1. Check if environment variables are set in Azure App Service
2. Restart the App Service after setting variables
3. Run `python manage.py set_build_info --auto` in App Service SSH
4. Check logs for version detection errors

### Version Information Not Updating
1. Clear browser cache
2. Restart the App Service
3. Check if `version_info.json` file exists and has correct data
4. Verify context processor is enabled in settings

### Environment Variables Not Working
1. Ensure variable names are exactly correct (case-sensitive)
2. Check for extra spaces in values
3. Restart App Service after changes
4. Use Azure CLI to verify settings: `az webapp config appsettings list`

## Files Modified
- `STATZWeb/version_utils.py`: Enhanced version detection
- `templates/base_template.html`: Added build number display
- `templates/landing.html`: Added build number display
- `templates/system_test.html`: Added build number display
- `STATZWeb/management/commands/set_build_info.py`: New management command
- `scripts/set_production_version.py`: Deployment script
- `scripts/azure-deployment-version.yml`: Azure DevOps pipeline step

## Benefits
- ✅ Works in both development and production
- ✅ Multiple fallback methods ensure version info is always available
- ✅ Easy to set up with environment variables
- ✅ Persistent storage prevents data loss
- ✅ Automatic build number generation
- ✅ Compatible with Azure DevOps and GitHub Actions
- ✅ No dependency on Git in production
