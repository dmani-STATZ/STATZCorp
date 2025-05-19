"""
Query Builder Module.

This module converts parsed natural language queries into Django ORM queries.
"""
from typing import Any, Dict, List, Optional, Tuple, Union
from django.db.models import Q, F, Count, Avg, Sum, Min, Max, QuerySet
from django.apps import apps

from .nlp_engine import (
    ParsedQuery, QueryType, AggregationType, FilterCondition
)

class QueryBuilder:
    """Class for building Django ORM queries from parsed natural language queries."""
    
    AGGREGATION_MAP = {
        AggregationType.COUNT: Count,
        AggregationType.SUM: Sum,
        AggregationType.AVG: Avg,
        AggregationType.MIN: Min,
        AggregationType.MAX: Max,
    }
    
    def __init__(self, metadata_reader):
        """Initialize with a metadata reader instance."""
        self.metadata_reader = metadata_reader
        self.nlp_engine = None  # Will be set by NLQueryView
    
    def set_nlp_engine(self, nlp_engine):
        """Set the NLP engine instance for field name normalization."""
        self.nlp_engine = nlp_engine
    
    def build_query(self, parsed_query: ParsedQuery) -> Tuple[QuerySet, Dict[str, Any]]:
        """Build a Django ORM query from a parsed query."""
        if not parsed_query.target_model:
            raise ValueError("No target model specified in the query")
        
        # Get the model class
        app_label, model_name = parsed_query.target_model.split('.')
        model = apps.get_model(app_label, model_name)
        
        # Start with a basic queryset
        queryset = model.objects.all()
        
        # Apply filters
        if parsed_query.filters:
            queryset = self._apply_filters(queryset, parsed_query.filters)
        
        # Handle different query types
        if parsed_query.query_type == QueryType.AGGREGATE:
            return self._build_aggregate_query(queryset, parsed_query)
        elif parsed_query.query_type == QueryType.GROUP:
            return self._build_group_query(queryset, parsed_query)
        elif parsed_query.query_type == QueryType.COMPLEX:
            return self._build_complex_query(queryset, parsed_query)
        else:  # LIST or FILTER
            return self._build_list_query(queryset, parsed_query)
    
    def _normalize_field_name(self, field_name: str) -> str:
        """Normalize a field name using the NLP engine if available."""
        if self.nlp_engine:
            return self.nlp_engine._normalize_field_name(field_name)
        return field_name
    
    def _apply_filters(self, queryset: QuerySet, filters: List[FilterCondition]) -> QuerySet:
        """Apply filter conditions to the queryset."""
        q_objects = Q()
        
        for filter_condition in filters:
            # Normalize the field name
            field = self._normalize_field_name(filter_condition.field)
            operator = filter_condition.operator
            value = filter_condition.value
            
            # Build the lookup based on operator
            if operator == '=':
                lookup = field
            elif operator == '!=':
                lookup = f"{field}__exact"
                q_objects &= ~Q(**{lookup: value})
                continue
            elif operator == '>':
                lookup = f"{field}__gt"
            elif operator == '<':
                lookup = f"{field}__lt"
            elif operator == 'BETWEEN':
                try:
                    min_val, max_val = value.split('and')
                    q_objects &= Q(**{
                        f"{field}__gte": min_val.strip(),
                        f"{field}__lte": max_val.strip()
                    })
                    continue
                except ValueError:
                    # Handle invalid BETWEEN values
                    continue
            else:
                # Skip unknown operators
                continue
            
            # Apply the filter
            q_objects &= Q(**{lookup: value})
        
        return queryset.filter(q_objects)
    
    def _build_list_query(
        self, queryset: QuerySet, parsed_query: ParsedQuery
    ) -> Tuple[QuerySet, Dict[str, Any]]:
        """Build a query for listing records."""
        # Select specific fields if specified
        if parsed_query.fields and '*' not in parsed_query.fields:
            # Normalize field names
            normalized_fields = [self._normalize_field_name(f) for f in parsed_query.fields]
            
            # For contract queries, always include id and contract_number for reference
            if parsed_query.target_model == 'contracts.contract':
                if 'id' not in normalized_fields:
                    normalized_fields.append('id')
                if 'contract_number' not in normalized_fields:
                    normalized_fields.append('contract_number')
                
            queryset = queryset.values(*normalized_fields)
        
        return self._apply_ordering_and_limit(queryset, parsed_query)
    
    def _build_aggregate_query(
        self, queryset: QuerySet, parsed_query: ParsedQuery
    ) -> Tuple[QuerySet, Dict[str, Any]]:
        """Build a query for aggregation operations."""
        annotations = {}
        
        for agg_type, field in parsed_query.aggregations:
            # Normalize the field name
            normalized_field = self._normalize_field_name(field)
            agg_class = self.AGGREGATION_MAP[agg_type]
            annotation_name = f"{agg_type.name.lower()}_{normalized_field}"
            annotations[annotation_name] = agg_class(normalized_field)
        
        if parsed_query.group_by:
            # Normalize group by fields
            normalized_group_by = [self._normalize_field_name(f) for f in parsed_query.group_by]
            queryset = queryset.values(*normalized_group_by)
        
        queryset = queryset.annotate(**annotations)
        
        return self._apply_ordering_and_limit(queryset, parsed_query)
    
    def _build_group_query(
        self, queryset: QuerySet, parsed_query: ParsedQuery
    ) -> Tuple[QuerySet, Dict[str, Any]]:
        """Build a query for grouping operations."""
        if not parsed_query.group_by:
            raise ValueError("Group by fields not specified")
        
        queryset = queryset.values(*parsed_query.group_by)
        
        # Add any annotations specified
        annotations = {}
        if parsed_query.aggregations:
            for agg_type, field in parsed_query.aggregations:
                agg_class = self.AGGREGATION_MAP[agg_type]
                annotation_name = f"{agg_type.name.lower()}_{field}"
                annotations[annotation_name] = agg_class(field)
            
            queryset = queryset.annotate(**annotations)
        
        return self._apply_ordering_and_limit(queryset, parsed_query)
    
    def _build_complex_query(
        self, queryset: QuerySet, parsed_query: ParsedQuery
    ) -> Tuple[QuerySet, Dict[str, Any]]:
        """Build a query combining multiple operations."""
        # Start with grouping if specified
        if parsed_query.group_by:
            queryset = queryset.values(*parsed_query.group_by)
        
        # Add annotations
        annotations = {}
        if parsed_query.aggregations:
            for agg_type, field in parsed_query.aggregations:
                agg_class = self.AGGREGATION_MAP[agg_type]
                annotation_name = f"{agg_type.name.lower()}_{field}"
                annotations[annotation_name] = agg_class(field)
            
            queryset = queryset.annotate(**annotations)
        
        return self._apply_ordering_and_limit(queryset, parsed_query)
    
    def _apply_ordering_and_limit(
        self, queryset: QuerySet, parsed_query: ParsedQuery
    ) -> Tuple[QuerySet, Dict[str, Any]]:
        """Apply ordering and limit to the queryset."""
        # Apply ordering
        if parsed_query.order_by:
            order_fields = []
            for field, direction in parsed_query.order_by:
                # Normalize the field name
                normalized_field = self._normalize_field_name(field)
                if direction == 'DESC':
                    order_fields.append(F(normalized_field).desc())
                else:
                    order_fields.append(F(normalized_field).asc())
            queryset = queryset.order_by(*order_fields)
        else:
            # Default ordering for contracts by contract_number
            if parsed_query.target_model == 'contracts.contract':
                queryset = queryset.order_by('contract_number')
        
        # Apply limit
        if parsed_query.limit is not None:
            queryset = queryset[:parsed_query.limit]
        
        # Return the queryset and any context needed for rendering
        context = {
            'query_type': parsed_query.query_type,
            'fields': [self._normalize_field_name(f) for f in (parsed_query.fields or [])],
            'group_by': [self._normalize_field_name(f) for f in (parsed_query.group_by or [])],
            'aggregations': [
                (agg_type, self._normalize_field_name(field))
                for agg_type, field in (parsed_query.aggregations or [])
            ],
        }
        
        return queryset, context

# Example usage:
"""
from reports.nli_reporting.metadata_reader import ORMMetadataReader
from reports.nli_reporting.nlp_engine import NLPEngine

# Initialize components
metadata_reader = ORMMetadataReader(['contracts'])
nlp_engine = NLPEngine(metadata_reader)
query_builder = QueryBuilder(metadata_reader)

# Parse and execute a query
query_text = "show top 5 suppliers by contract count order by count descending"
parsed_query = nlp_engine.parse_query(query_text)
queryset, context = query_builder.build_query(parsed_query)

# Use the queryset
results = list(queryset)
""" 