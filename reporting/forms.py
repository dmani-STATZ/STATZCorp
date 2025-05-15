from django import forms
from django.contrib.contenttypes.models import ContentType
from django.apps import apps
from django.db.models import ForeignKey, IntegerField, FloatField, DecimalField
from contracts.models import (
    Contract, Clin, IdiqContract, ContractStatus, Buyer, 
    ContractType, SalesClass, ContractSplit, PaymentHistory,
    Supplier, Nsn, Note, CanceledReason
)

class ReportCreationForm(forms.Form):
    """Form for creating a report with multiple table and field selection."""
    
    # Available models from the contracts app
    AVAILABLE_MODELS = {
        'contract': Contract,
        'clin': Clin,
        'idiq_contract': IdiqContract,
        'contract_status': ContractStatus,
        'buyer': Buyer,
        'contract_type': ContractType,
        'sales_class': SalesClass,
        'contract_split': ContractSplit,
        'payment_history': PaymentHistory,
        'supplier': Supplier,
        'nsn': Nsn,
        'note': Note,
        'canceled_reason': CanceledReason,
    }
    
    # Hidden fields to store selected tables and fields as JSON
    selected_tables = forms.CharField(
        widget=forms.HiddenInput(),
        required=False
    )
    
    selected_fields = forms.CharField(
        widget=forms.HiddenInput(),
        required=False
    )
    
    filters = forms.CharField(
        widget=forms.HiddenInput(),
        required=False
    )
    
    sort_by = forms.CharField(
        widget=forms.HiddenInput(),
        required=False
    )
    
    sort_direction = forms.CharField(
        widget=forms.HiddenInput(),
        required=False,
        initial='asc'
    )
    
    aggregations = forms.CharField(
        widget=forms.HiddenInput(),
        required=False
    )
    
    report_name = forms.CharField(
        max_length=100,
        required=True,
        widget=forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Enter report name'})
    )
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.model_relationships = self._get_model_relationships()
    
    def _get_model_relationships(self):
        """
        Build a dictionary of relationships between models.
        Returns a dict where keys are model names and values are lists of related models.
        """
        relationships = {}
        
        for model_name, model_class in self.AVAILABLE_MODELS.items():
            relationships[model_name] = []
            
            # Get all fields that are ForeignKey relationships
            for field in model_class._meta.get_fields():
                if isinstance(field, ForeignKey):
                    # Find the related model name in AVAILABLE_MODELS
                    related_model_name = None
                    for available_name, available_model in self.AVAILABLE_MODELS.items():
                        if available_model == field.related_model:
                            related_model_name = available_name
                            break
                    
                    if related_model_name:
                        relationships[model_name].append({
                            'model': related_model_name,
                            'field': field.name
                        })
        
        return relationships
    
    def get_linking_tables(self, selected_tables):
        """
        Find tables needed to link the selected tables if they're not directly related.
        Returns a list of additional tables needed.
        """
        if len(selected_tables) < 2:
            return []
            
        needed_tables = set()
        selected_set = set(selected_tables)
        
        # For each pair of selected tables
        for i, table1 in enumerate(selected_tables):
            for table2 in selected_tables[i+1:]:
                # If tables are directly related, skip
                if any(rel['model'] == table2 for rel in self.model_relationships[table1]):
                    continue
                    
                # Find intermediate tables that can connect these tables
                for model_name, relations in self.model_relationships.items():
                    if (model_name not in selected_set and
                        any(rel['model'] == table1 for rel in relations) and
                        any(rel['model'] == table2 for rel in relations)):
                        needed_tables.add(model_name)
        
        return list(needed_tables)
    
    def get_available_fields(self, selected_tables):
        """
        Get all available fields from the selected tables.
        Returns a dict where keys are table names and values are lists of field information.
        """
        fields = {}
        numeric_types = (IntegerField, FloatField, DecimalField)
        
        # First, process each table's own fields
        for table in selected_tables:
            if table in self.AVAILABLE_MODELS:
                model_class = self.AVAILABLE_MODELS[table]
                fields[table] = []
                
                # Add regular fields
                for field in model_class._meta.fields:
                    # Skip primary keys of related models to avoid confusion
                    if field.is_relation and field.primary_key:
                        continue
                        
                    field_info = {
                        'name': field.name,
                        'verbose_name': field.verbose_name.title(),
                        'type': field.get_internal_type(),
                        'supports_aggregation': isinstance(field, numeric_types)
                    }
                    
                    if isinstance(field, ForeignKey):
                        field_info['related_model'] = field.related_model._meta.model_name
                    
                    fields[table].append(field_info)
        
        # Then, process related fields in a separate pass
        for table in selected_tables:
            if table in self.AVAILABLE_MODELS:
                model_class = self.AVAILABLE_MODELS[table]
                
                # Add related fields
                for field in model_class._meta.get_fields():
                    if field.is_relation and not field.many_to_many and not field.one_to_many:
                        # Get the related model name
                        related_model_name = None
                        for model_key, model_val in self.AVAILABLE_MODELS.items():
                            if model_val == field.related_model:
                                related_model_name = model_key
                                break
                        
                        if related_model_name and related_model_name in selected_tables:
                            # Add the relation field itself
                            field_info = {
                                'name': field.name,
                                'verbose_name': field.verbose_name.title(),
                                'type': 'RelatedField',
                                'related_model': related_model_name
                            }
                            fields[table].append(field_info)
                            
                            # Add fields from the related model
                            for related_field in field.related_model._meta.fields:
                                if not related_field.is_relation or not related_field.primary_key:
                                    field_info = {
                                        'name': f"{field.name}__{related_field.name}",
                                        'verbose_name': f"{field.verbose_name.title()} - {related_field.verbose_name.title()}",
                                        'type': related_field.get_internal_type(),
                                        'supports_aggregation': isinstance(related_field, numeric_types)
                                    }
                                    fields[table].append(field_info)
        
        return fields

    def clean(self):
        cleaned_data = super().clean()
        import json
        
        # Parse selected_tables
        selected_tables_raw = cleaned_data.get('selected_tables')
        try:
            selected_tables = json.loads(selected_tables_raw) if selected_tables_raw else []
        except Exception:
            self.add_error('selected_tables', 'Invalid table selection.')
            selected_tables = []
        if not selected_tables:
            self.add_error('selected_tables', 'Please select at least one table.')
        cleaned_data['selected_tables'] = selected_tables

        # Parse selected_fields
        selected_fields_raw = cleaned_data.get('selected_fields')
        try:
            selected_fields = json.loads(selected_fields_raw) if selected_fields_raw else {}
            # Ensure it's a dictionary
            if not isinstance(selected_fields, dict):
                self.add_error('selected_fields', 'Invalid field selection format.')
                selected_fields = {}
            # Validate that all tables in selected_fields exist in selected_tables
            for table in selected_fields.keys():
                if table not in selected_tables:
                    self.add_error('selected_fields', f'Selected fields contain invalid table: {table}')
        except Exception:
            self.add_error('selected_fields', 'Invalid field selection.')
            selected_fields = {}
        if not selected_fields:
            self.add_error('selected_fields', 'Please select at least one field.')
        cleaned_data['selected_fields'] = selected_fields

        # Parse filters
        filters_raw = cleaned_data.get('filters')
        try:
            filters = json.loads(filters_raw) if filters_raw else []
        except Exception:
            self.add_error('filters', 'Invalid filters.')
            filters = []
        cleaned_data['filters'] = filters

        # Parse sort configuration
        sort_by_raw = cleaned_data.get('sort_by')
        sort_direction = cleaned_data.get('sort_direction', 'asc')
        try:
            sort_by = json.loads(sort_by_raw) if sort_by_raw else {}
            # Validate sort configuration
            if sort_by:
                # Ensure it's a dictionary with table -> {field, direction} structure
                if not isinstance(sort_by, dict):
                    self.add_error('sort_by', 'Invalid sort configuration format.')
                    sort_by = {}
                else:
                    # Validate each table's sort config
                    for table, config in sort_by.items():
                        if not isinstance(config, dict) or 'field' not in config:
                            self.add_error('sort_by', f'Invalid sort configuration for table: {table}')
                            sort_by = {}
                            break
                        # Validate that the table exists in selected tables
                        if table not in selected_tables:
                            self.add_error('sort_by', f'Sort configuration contains invalid table: {table}')
                            sort_by = {}
                            break
        except Exception:
            self.add_error('sort_by', 'Invalid sort configuration.')
            sort_by = {}
        cleaned_data['sort_by'] = sort_by
        
        # Validate sort direction
        if sort_direction not in ['asc', 'desc']:
            cleaned_data['sort_direction'] = 'asc'
        else:
            cleaned_data['sort_direction'] = sort_direction

        # Parse aggregations
        aggregations_raw = cleaned_data.get('aggregations')
        try:
            aggregations = json.loads(aggregations_raw) if aggregations_raw else {}
            # Validate aggregations structure
            if not isinstance(aggregations, dict):
                self.add_error('aggregations', 'Invalid aggregations format.')
                aggregations = {}
            else:
                # Validate each aggregation config
                for field_path, config in aggregations.items():
                    if not isinstance(config, dict) or 'type' not in config:
                        self.add_error('aggregations', f'Invalid aggregation configuration for field: {field_path}')
                        aggregations = {}
                        break
                    # Validate aggregation type
                    if config['type'] not in ['sum', 'avg', 'min', 'max', 'count']:
                        self.add_error('aggregations', f'Invalid aggregation type for field: {field_path}')
                        aggregations = {}
                        break
        except Exception as e:
            self.add_error('aggregations', f'Invalid aggregations configuration: {str(e)}')
            aggregations = {}
        cleaned_data['aggregations'] = aggregations

        return cleaned_data 