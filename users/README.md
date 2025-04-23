## Users Application Process Write-up

**Objective:** The `users` application manages user authentication, profiles, application-level permissions, and user-specific settings within the STATZWeb project.

**Key Components:**

1.  **Models (`users/models.py`):
    *   `User` (Django Built-in): Standard Django user model.
    *   `Announcement`: For site-wide announcements.
    *   `AppRegistry`: Registers other Django applications within the project to be used in the permission system.
    *   `AppPermission`: Links a `User` to an `AppRegistry` entry, granting or denying access (`has_access`) to specific applications.
    *   `UserSetting`: Defines available user settings (name, type, default value).
    *   `UserSettingState`: Stores the specific value of a `UserSetting` for a particular `User`.

2.  **Authentication (`users/views.py`, `users/ms_views.py`, `users/azure_auth.py`):
    *   Primary method is **Microsoft Azure AD Authentication**.
    *   `MicrosoftAuthView`: Initiates the OAuth2 flow with Azure AD.
    *   `MicrosoftCallbackView`: Handles the callback from Azure AD after authentication, logs the user in, and potentially creates/updates the local Django `User` record.
    *   `login_view`: Orchestrates the login process, primarily redirecting non-admin users to the Microsoft login flow (`users:microsoft_login`).
    *   Admin Login: A traditional Django username/password login form is available for users marked as `is_staff` via the `/login/?admin_mode=1` URL or specific POST parameters.
    *   Registration: The standard registration view (`/register/`) is effectively disabled, directing users to authenticate via Microsoft.
    *   Logout: Uses Django's standard `LogoutView`.
    *   Password Reset: Standard Django password reset views are included but may have limited use due to Microsoft authentication being primary.

3.  **User Settings System (`users/user_settings.py`, `users/views.py`):
    *   `UserSettings` Class: Provides a centralized API (class methods) to get, save, and manage user settings based on the `UserSetting` and `UserSettingState` models.
    *   Handles type conversions (string, boolean, integer, json).
    *   `manage_settings` View (`/settings/view/`): Renders a page (`users/manage_settings.html`) allowing users (likely admins) to view and modify settings for themselves and potentially other users.
    *   AJAX Endpoints (`/settings/ajax/...`): Support the `manage_settings` page for dynamically getting and saving settings without full page reloads.

4.  **Application Permissions (`users/models.py`, `STATZWeb/decorators.py`):
    *   Uses `AppRegistry` and `AppPermission` models to define which users have access to which registered applications.
    *   A custom decorator (likely `@app_access_required` in `STATZWeb/decorators.py`, although not directly reviewed here) probably checks `AppPermission` records before allowing access to views in other applications.
    *   `permission_denied` View (`/permission-denied/`): Displays an error page if a user lacks the necessary app permissions.

5.  **Profile (`users/views.py` - URL likely defined elsewhere):
    *   `profile` View: A basic view (protected by `@login_required`) to display user profile information (`users/profile.html`). The specific URL mapping needs confirmation (potentially in the main project `urls.py`).

6.  **URLs (`users/urls.py`):
    *   Defines paths for login, logout, password reset, Microsoft authentication, settings management, permission denial, and debugging views.

7.  **Admin (`users/admin.py`):
    *   Provides Django admin interfaces for managing `User`, `Announcement`, `AppRegistry`, `AppPermission`, `UserSetting`, and `UserSettingState` models.

**Core Processes:**

1.  **Authentication:**
    *   Most users access `/login/` and are redirected to Microsoft for authentication.
    *   Upon successful Microsoft login, they are redirected back to the application (`/microsoft/callback/`), logged into their corresponding Django user account, and typically sent to the index page.
    *   Admin users can bypass Microsoft login via a specific URL/parameter to use the Django username/password form.
2.  **Authorization (App Access):**
    *   When a user tries to access a view in another application (e.g., `contracts`, `inventory`), a decorator likely checks their `AppPermission` record for that application.
    *   If `has_access` is `True`, the view proceeds.
    *   If `has_access` is `False` or no record exists, the user is redirected to the `/permission-denied/` page.
3.  **User Settings Management:**
    *   Users (or admins) navigate to `/settings/view/`.
    *   The page displays defined settings and their current values for the selected user.
    *   Changes are made via interactive elements (text boxes, dropdowns) which trigger AJAX calls (`/settings/ajax/save/`, `/settings/ajax/get/`) to update the `UserSettingState` records via the `UserSettings` class.
4.  **Profile Viewing:** Users access their profile page (URL TBD) to view their basic information.
5.  **Admin Management:** Administrators use the Django admin interface (`/admin/`) to manage users, announcements, app registrations, app permissions, and user setting definitions/states directly.

This application provides robust user management focused on Azure AD integration, a flexible settings system, and a custom mechanism for controlling access to different parts of the larger STATZWeb project. 