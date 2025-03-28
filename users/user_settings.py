from typing import Any, Optional, Dict, Union

class UserSettings:
    """
    A class to manage user settings using UserSetting and UserSettingState models.
    
    Usage:
        # Get a setting value
        value = UserSettings.get_setting(user, "setting_name")
        
        # Save a setting value
        UserSettings.save_setting(user, "setting_name", value)
        
        # Get multiple settings at once
        settings = UserSettings.get_multiple_settings(user, ["setting1", "setting2"])
        
        # Save multiple settings at once
        UserSettings.save_multiple_settings(user, {"setting1": "value1", "setting2": "value2"})
    """
    
    @classmethod
    def _get_or_create_setting(cls, name: str, setting_type: str = 'string', 
                             default_value: Any = '', description: str = '', 
                             is_global: bool = False) -> Any:
        """
        Get or create a UserSetting entry.
        
        Args:
            name: The name of the setting
            setting_type: The type of setting (string, boolean, integer, etc.)
            default_value: Default value for the setting
            description: Description of what the setting does
            is_global: Whether this is a global setting
            
        Returns:
            UserSetting object
        """
        # Import here to avoid circular imports
        from .models import UserSetting
        
        setting, _ = UserSetting.objects.get_or_create(
            name=name,
            defaults={
                'setting_type': setting_type,
                'default_value': str(default_value),
                'description': description or f'Setting for {name}',
                'is_global': is_global
            }
        )
        return setting

    @classmethod
    def _get_or_create_setting_state(cls, user: Any, setting: Any, 
                                   value: Optional[Any] = None) -> Any:
        """
        Get or create a UserSettingState entry.
        
        Args:
            user: The user to get/create the setting for
            setting: The UserSetting object
            value: Optional value to set
            
        Returns:
            UserSettingState object
        """
        # Import here to avoid circular imports
        from .models import UserSettingState
        
        state, created = UserSettingState.objects.get_or_create(
            user=user,
            setting=setting,
            defaults={'value': str(value) if value is not None else setting.default_value}
        )
        
        if not created and value is not None:
            state.value = str(value)
            state.save()
            
        return state

    @classmethod
    def get_setting(cls, user: Any, name: str, default: Any = None) -> Any:
        """
        Get a user setting value.
        
        Args:
            user: The user to get the setting for
            name: The name of the setting
            default: Default value if setting doesn't exist
            
        Returns:
            The setting value
        """
        try:
            setting = cls._get_or_create_setting(name)
            state = cls._get_or_create_setting_state(user, setting)
            return state.get_value()
        except Exception as e:
            print(f"Error getting setting {name}: {str(e)}")
            return default

    @classmethod
    def save_setting(cls, user: Any, name: str, value: Any, 
                    setting_type: str = 'string', description: str = '', 
                    is_global: bool = False) -> bool:
        """
        Save a user setting value.
        
        Args:
            user: The user to save the setting for
            name: The name of the setting
            value: The value to save
            setting_type: The type of setting
            description: Description of what the setting does
            is_global: Whether this is a global setting
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            setting = cls._get_or_create_setting(
                name, 
                setting_type=setting_type,
                description=description,
                is_global=is_global
            )
            cls._get_or_create_setting_state(user, setting, value)
            return True
        except Exception as e:
            print(f"Error saving setting {name}: {str(e)}")
            return False

    @classmethod
    def get_multiple_settings(cls, user: Any, names: list[str]) -> Dict[str, Any]:
        """
        Get multiple settings at once.
        
        Args:
            user: The user to get settings for
            names: List of setting names to retrieve
            
        Returns:
            Dict of setting names and their values
        """
        return {name: cls.get_setting(user, name) for name in names}

    @classmethod
    def save_multiple_settings(cls, user: Any, settings: Dict[str, Any]) -> bool:
        """
        Save multiple settings at once.
        
        Args:
            user: The user to save settings for
            settings: Dict of setting names and values to save
            
        Returns:
            bool: True if all settings were saved successfully
        """
        success = True
        for name, value in settings.items():
            if not cls.save_setting(user, name, value):
                success = False
        return success

    @classmethod
    def delete_setting(cls, user: Any, name: str) -> bool:
        """
        Delete a user setting.
        
        Args:
            user: The user to delete the setting for
            name: The name of the setting
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Import here to avoid circular imports
            from .models import UserSetting, UserSettingState
            
            setting = UserSetting.objects.get(name=name)
            UserSettingState.objects.filter(user=user, setting=setting).delete()
            return True
        except Exception as e:
            print(f"Error deleting setting {name}: {str(e)}")
            return False

    @classmethod
    def clear_all_settings(cls, user: Any) -> bool:
        """
        Clear all settings for a user.
        
        Args:
            user: The user to clear settings for
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Import here to avoid circular imports
            from .models import UserSettingState
            
            UserSettingState.objects.filter(user=user).delete()
            return True
        except Exception as e:
            print(f"Error clearing settings: {str(e)}")
            return False

    @classmethod
    def get_all_settings(cls, user: Any) -> Dict[str, Any]:
        """
        Get all settings for a user.
        
        Args:
            user: The user to get settings for
            
        Returns:
            Dict of all setting names and their values
        """
        try:
            # Import here to avoid circular imports
            from .models import UserSettingState
            
            states = UserSettingState.objects.filter(user=user).select_related('setting')
            return {state.setting.name: state.get_value() for state in states}
        except Exception as e:
            print(f"Error getting all settings: {str(e)}")
            return {} 