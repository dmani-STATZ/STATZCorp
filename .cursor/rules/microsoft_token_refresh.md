# How to Get a Valid Microsoft Access Token for API Calls

## Overview

When you need to make calls to Microsoft APIs (like Microsoft Graph) on behalf of the currently logged-in user, you must use their OAuth access token. These tokens expire, so you cannot simply store the initial token and reuse it indefinitely.

The `users` app provides a utility function, `get_valid_microsoft_token`, to handle this process automatically.

## Key Function

- **`get_valid_microsoft_token(user: User) -> str | None`**
  - Located in: `users.azure_auth`
  - **Purpose**: Retrieves a currently valid Microsoft access token for the specified user.
  - **Behavior**:
    1. Fetches the stored `UserOAuthToken` for the user.
    2. Checks if the `access_token` has expired using the `is_expired` property.
    3. If the token is **not expired**, it returns the existing `access_token`.
    4. If the token **is expired** and a `refresh_token` is available, it attempts to use the refresh token to get a new `access_token` and `refresh_token` from Microsoft.
    5. If the refresh is **successful**, it updates the stored `UserOAuthToken` record with the new details and returns the new `access_token`.
    6. If the token is expired and **no refresh token** is available, or if the **refresh attempt fails**, it logs an error and returns `None`.
  - **Return Value**: A valid `access_token` string if successful, otherwise `None`.

## Usage Example

Here's how to use the function within a Django view or other code where you have access to the `request.user` object:

```python
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
import requests
from users.azure_auth import get_valid_microsoft_token
import logging

logger = logging.getLogger(__name__)

@login_required
def get_user_profile_from_graph(request):
    user = request.user
    context = {}

    # Get a valid token, handling refresh automatically
    access_token = get_valid_microsoft_token(user)

    if not access_token:
        logger.error(f"Could not obtain a valid Microsoft token for user {user.username}")
        context['error'] = "Authentication token is unavailable. Please try logging out and back in."
        return render(request, 'profile_display.html', context)

    # Use the token to call Microsoft Graph API
    graph_url = "https://graph.microsoft.com/v1.0/me"
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json'
    }

    try:
        response = requests.get(graph_url, headers=headers)
        response.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)
        profile_data = response.json()
        context['profile'] = profile_data
        logger.info(f"Successfully retrieved Graph profile for {user.username}")

    except requests.exceptions.RequestException as e:
        logger.error(f"Microsoft Graph API request failed for user {user.username}: {e}")
        context['error'] = f"Failed to retrieve profile data from Microsoft: {e}"
    except Exception as e:
        logger.exception(f"An unexpected error occurred retrieving profile for {user.username}")
        context['error'] = "An unexpected error occurred."

    return render(request, 'profile_display.html', context)

```

## Key Takeaways

- **Always** use `get_valid_microsoft_token(user)` when you need an access token for Microsoft API calls.
- **Do not** directly access `user.oauth_token.access_token` for API calls, as it might be expired.
- **Always** check if the returned value is `None` and handle that case appropriately (e.g., show an error message, ask the user to re-authenticate).
- This function centralizes the logic for checking expiry and performing refreshes. 