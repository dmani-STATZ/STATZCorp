"""
ORM Metadata Reader.

This module provides functionality to read metadata about Django models
to support natural language query processing.
"""
from typing import Dict, List, Set
from dataclasses import dataclass
from django.apps import apps
from django.db.models import Model, Field, ForeignKey, ManyToManyField

@dataclass
class ModelMetadata:
    """Class holding metadata about a Django model."""
    fields: Dict[str, str]  # field_name -> field_type
    relationships: Dict[str, str]  # field_name -> related_model

class ORMMetadataReader:
    """Class for reading metadata about Django models."""
    
    def __init__(self, app_names: List[str]):
        """Initialize with a list of app names to read metadata from."""
        self.models = {}
        self._load_models(app_names)
    
    def _load_models(self, app_names: List[str]):
        """Load metadata for all models in the specified apps."""
        for app_name in app_names:
            app_config = apps.get_app_config(app_name)
            for model in app_config.get_models():
                model_key = f"{app_name}.{model.__name__.lower()}"
                self.models[model_key] = self._get_model_metadata(model)
    
    def _get_model_metadata(self, model: Model) -> ModelMetadata:
        """Get metadata for a specific model."""
        fields = {}
        relationships = {}
        
        for field in model._meta.get_fields():
            if isinstance(field, (ForeignKey, ManyToManyField)):
                relationships[field.name] = field.related_model.__name__.lower()
            elif isinstance(field, Field):
                fields[field.name] = field.get_internal_type()
        
        return ModelMetadata(fields=fields, relationships=relationships)
    
    def get_model_fields(self, model_key: str) -> Set[str]:
        """Get all field names for a specific model."""
        if model_key not in self.models:
            return set()
        
        metadata = self.models[model_key]
        return set(metadata.fields.keys()) | set(metadata.relationships.keys())
    
    def get_field_type(self, model_key: str, field_name: str) -> str:
        """Get the type of a specific field."""
        if model_key not in self.models:
            return None
        
        metadata = self.models[model_key]
        return metadata.fields.get(field_name) or metadata.relationships.get(field_name)
    
    def get_all_field_names(self) -> Set[str]:
        """Get all field names across all models."""
        field_names = set()
        for metadata in self.models.values():
            field_names.update(metadata.fields.keys())
            field_names.update(metadata.relationships.keys())
        return field_names
    
    def get_related_model(self, model_key: str, field_name: str) -> str:
        """Get the related model for a relationship field."""
        if model_key not in self.models:
            return None
        
        metadata = self.models[model_key]
        return metadata.relationships.get(field_name)

    def find_models_with_field(self, field_name: str) -> List[str]:
        """Find all models that have a specific field."""
        models_with_field = []
        
        # Look for the field in all models
        for model in self.get_all_models():
            if any(field.name == field_name for field in model._meta.fields):
                models_with_field.append(model.__name__)
        
        return models_with_field

    def find_date_fields(self) -> Dict[str, List[str]]:
        """Find all date/time fields in the models."""
        date_fields = {}
        
        for model in self.get_all_models():
            model_date_fields = []
            for field in model._meta.fields:
                if isinstance(field, (models.DateField, models.DateTimeField)):
                    model_date_fields.append(field.name)
            if model_date_fields:
                date_fields[model.__name__] = model_date_fields
        
        return date_fields

# Example usage:
"""
# Initialize the metadata reader
reader = ORMMetadataReader(['contracts'])

# Get metadata for a specific model
contract_metadata = reader.get_model_metadata('contracts', 'contract')

# Find all models with a specific field
models_with_date = reader.find_models_with_field('timestamp')

# Get all field names
all_fields = reader.get_all_field_names()

# Get related models
related_models = reader.get_related_models('contracts', 'contract')
""" 