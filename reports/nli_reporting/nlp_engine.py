"""
Natural Language Processing Engine.

This module provides functionality to parse natural language queries into structured
representations that can be used to build Django ORM queries.
"""
from typing import Dict, List, Optional, Set, Tuple
import re
from dataclasses import dataclass
from enum import Enum, auto

class QueryType(Enum):
    """Enum representing different types of queries."""
    LIST = auto()  # Simple listing of records
    AGGREGATE = auto()  # Aggregation queries (count, sum, avg, etc.)
    FILTER = auto()  # Queries with conditions
    GROUP = auto()  # Queries with grouping
    COMPLEX = auto()  # Queries combining multiple types

class AggregationType(Enum):
    """Enum representing different types of aggregations."""
    COUNT = auto()
    SUM = auto()
    AVG = auto()
    MIN = auto()
    MAX = auto()

@dataclass
class FilterCondition:
    """Class representing a filter condition."""
    field: str
    operator: str
    value: str
    connector: Optional[str] = 'AND'  # AND/OR

@dataclass
class ParsedQuery:
    """Class representing a parsed natural language query."""
    query_type: QueryType
    target_model: Optional[str] = None
    fields: List[str] = None
    filters: List[FilterCondition] = None
    aggregations: List[Tuple[AggregationType, str]] = None
    group_by: List[str] = None
    order_by: List[Tuple[str, str]] = None  # (field, direction)
    limit: Optional[int] = None

class NLPEngine:
    """Main class for parsing natural language queries."""
    
    # Common words indicating query types
    AGGREGATION_KEYWORDS = {
        'count': AggregationType.COUNT,
        'sum': AggregationType.SUM,
        'total': AggregationType.SUM,
        'average': AggregationType.AVG,
        'avg': AggregationType.AVG,
        'minimum': AggregationType.MIN,
        'min': AggregationType.MIN,
        'maximum': AggregationType.MAX,
        'max': AggregationType.MAX,
    }
    
    OPERATOR_KEYWORDS = {
        'greater than': '>',
        'more than': '>',
        'over': '>',
        'less than': '<',
        'under': '<',
        'equal to': '=',
        'equals': '=',
        'is': '=',
        'not equal to': '!=',
        'between': 'BETWEEN',
    }
    
    ORDER_KEYWORDS = {
        'ascending': 'ASC',
        'descending': 'DESC',
        'asc': 'ASC',
        'desc': 'DESC',
    }
    
    # Field name mappings for common variations
    FIELD_MAPPINGS = {
        # Contract number variations
        'number': 'contract_number',
        'contract number': 'contract_number',
        'contractnumber': 'contract_number',
        'contract_num': 'contract_number',
        'contract num': 'contract_number',
        
        # PO number variations
        'po': 'po_number',
        'po number': 'po_number',
        'purchase order': 'po_number',
        'purchase order number': 'po_number',
        'ponumber': 'po_number',
        
        # Status variations
        'contract status': 'status',
        
        # Value variations
        'value': 'contract_value',
        'contract value': 'contract_value',
        'amount': 'contract_value',
        'contract amount': 'contract_value',
        
        # Date variations
        'date': 'created_on',
        'created': 'created_on',
        'creation date': 'created_on',
        'modified': 'modified_on',
        'modified date': 'modified_on',
        'last modified': 'modified_on',
        'due': 'due_date',
        'awarded': 'award_date',
        'award': 'award_date',
        
        # User variations
        'created by': 'created_by',
        'creator': 'created_by',
        'author': 'created_by',
        'modified by': 'modified_by',
        'modifier': 'modified_by',
        'reviewed by': 'reviewed_by',
        'reviewer': 'reviewed_by',
        
        # Other common variations
        'type': 'contract_type',
        'contract type': 'contract_type',
        'notes': 'notes',
        'comment': 'notes',
        'comments': 'notes',
        'buyer': 'buyer',
        'purchaser': 'buyer',
        'assigned': 'assigned_user',
        'assigned to': 'assigned_user',
        'owner': 'assigned_user'
    }
    
    def __init__(self, metadata_reader):
        """Initialize with a metadata reader instance."""
        self.metadata_reader = metadata_reader
        self._compile_patterns()
        self._build_field_variations()
    
    def _compile_patterns(self):
        """Compile regex patterns for query parsing."""
        # Pattern for finding aggregations
        agg_words = '|'.join(self.AGGREGATION_KEYWORDS.keys())
        self.aggregation_pattern = re.compile(
            f"({agg_words})\\s+(?:of\\s+)?([\\w_]+)",
            re.IGNORECASE
        )
        
        # Pattern for finding operators
        op_words = '|'.join(self.OPERATOR_KEYWORDS.keys())
        self.operator_pattern = re.compile(
            f"([\\w_]+)\\s+({op_words})\\s+([\\w\\s]+)",
            re.IGNORECASE
        )
        
        # Pattern for finding order by clauses
        order_words = '|'.join(self.ORDER_KEYWORDS.keys())
        self.order_pattern = re.compile(
            f"order\\s+by\\s+([\\w_]+)\\s+({order_words})",
            re.IGNORECASE
        )
        
        # Pattern for finding specific fields
        self.field_pattern = re.compile(
            r"by\s+([\w_,\s]+)(?:\s+|$)",
            re.IGNORECASE
        )
    
    def _build_field_variations(self):
        """Build additional field variations based on actual model fields."""
        model_fields = self.metadata_reader.get_model_fields('contracts.contract')
        
        # Add variations for each actual field
        for field in model_fields:
            # Add version without underscores
            no_underscore = field.replace('_', ' ')
            if no_underscore != field:
                self.FIELD_MAPPINGS[no_underscore] = field
            
            # Add version without spaces
            no_space = field.replace(' ', '')
            if no_space != field:
                self.FIELD_MAPPINGS[no_space] = field
            
            # Add individual words if field has multiple parts
            parts = field.split('_')
            if len(parts) > 1:
                # Add last part as a variation if it's meaningful
                if len(parts[-1]) > 2:  # Avoid too short words
                    self.FIELD_MAPPINGS[parts[-1]] = field
    
    def _normalize_field_name(self, field_name: str) -> str:
        """Normalize a field name to match the actual model field name."""
        # Convert to lowercase and remove extra spaces
        normalized = field_name.lower().strip()
        
        # Check direct mapping
        if normalized in self.FIELD_MAPPINGS:
            return self.FIELD_MAPPINGS[normalized]
        
        # Try without spaces
        no_spaces = normalized.replace(' ', '')
        if no_spaces in self.FIELD_MAPPINGS:
            return self.FIELD_MAPPINGS[no_spaces]
        
        # Try with underscores instead of spaces
        with_underscores = normalized.replace(' ', '_')
        if with_underscores in self.metadata_reader.get_model_fields('contracts.contract'):
            return with_underscores
        
        # If no match found, return original (will be validated later)
        return field_name
    
    def parse_query(self, query_text: str) -> ParsedQuery:
        """Parse a natural language query into a structured format."""
        query_text = query_text.lower().strip()
        
        # Always set contracts.contract as the target model
        target_model = 'contracts.contract'
        
        # Determine query type
        query_type = self._determine_query_type(query_text)
        
        # Extract fields
        fields = self._extract_fields(query_text)
        
        # Extract filters
        filters = self._extract_filters(query_text)
        
        # Extract aggregations
        aggregations = self._extract_aggregations(query_text)
        
        # Extract group by
        group_by = self._extract_group_by(query_text)
        
        # Extract order by
        order_by = self._extract_order_by(query_text)
        
        # Extract limit
        limit = self._extract_limit(query_text)
        
        return ParsedQuery(
            query_type=query_type,
            target_model=target_model,
            fields=fields,
            filters=filters,
            aggregations=aggregations,
            group_by=group_by,
            order_by=order_by,
            limit=limit
        )
    
    def _determine_query_type(self, query_text: str) -> QueryType:
        """Determine the type of query based on keywords and structure."""
        if any(word in query_text for word in self.AGGREGATION_KEYWORDS):
            return QueryType.AGGREGATE
        elif 'group by' in query_text:
            return QueryType.GROUP
        elif any(word in query_text for word in self.OPERATOR_KEYWORDS):
            return QueryType.FILTER
        elif all(word in query_text for word in ['count', 'group']):
            return QueryType.COMPLEX
        return QueryType.LIST
    
    def _extract_fields(self, query_text: str) -> List[str]:
        """Extract the fields to be returned from the query."""
        # First try to find fields after "by" keyword
        match = self.field_pattern.search(query_text)
        if match:
            raw_fields = [f.strip() for f in match.group(1).split(',')]
            # Normalize and validate fields
            valid_fields = []
            for field in raw_fields:
                normalized_field = self._normalize_field_name(field)
                if normalized_field in self.metadata_reader.get_model_fields('contracts.contract'):
                    valid_fields.append(normalized_field)
            if valid_fields:
                return valid_fields
        
        # Look for field names in the query
        fields = []
        model_fields = self.metadata_reader.get_model_fields('contracts.contract')
        words = query_text.lower().split()
        
        # Try to match each word or pair of words against our field mappings
        i = 0
        while i < len(words):
            # Try two-word combinations first
            if i < len(words) - 1:
                two_words = ' '.join(words[i:i+2])
                normalized = self._normalize_field_name(two_words)
                if normalized in model_fields:
                    fields.append(normalized)
                    i += 2
                    continue
            
            # Try single words
            normalized = self._normalize_field_name(words[i])
            if normalized in model_fields:
                fields.append(normalized)
            i += 1
        
        # If no fields found but query mentions contracts, return contract_number
        if not fields and 'contract' in query_text.lower():
            return ['contract_number']
        
        return fields or ['*']  # Return all fields if none specified
    
    def _extract_filters(self, query_text: str) -> List[FilterCondition]:
        """Extract filter conditions from the query."""
        filters = []
        matches = self.operator_pattern.finditer(query_text)
        
        for match in matches:
            field, operator_text, value = match.groups()
            operator = self.OPERATOR_KEYWORDS.get(operator_text)
            if operator:
                # Try to convert value to number if it looks like one
                try:
                    value = float(value.strip())
                except ValueError:
                    value = value.strip()
                filters.append(FilterCondition(field, operator, value))
        
        return filters
    
    def _extract_aggregations(self, query_text: str) -> List[Tuple[AggregationType, str]]:
        """Extract aggregation operations from the query."""
        aggregations = []
        matches = self.aggregation_pattern.finditer(query_text)
        
        for match in matches:
            agg_type_text, field = match.groups()
            agg_type = self.AGGREGATION_KEYWORDS.get(agg_type_text.lower())
            if agg_type:
                aggregations.append((agg_type, field))
        
        return aggregations
    
    def _extract_group_by(self, query_text: str) -> List[str]:
        """Extract group by fields from the query."""
        if 'group by' not in query_text:
            return []
        
        # Extract everything after 'group by'
        group_by_text = query_text.split('group by')[-1].split('order by')[0]
        fields = []
        
        # Look for field names in the group by clause
        model_fields = self.metadata_reader.get_model_fields('contracts.contract')
        for field in model_fields:
            if field in group_by_text:
                fields.append(field)
        
        return fields
    
    def _extract_order_by(self, query_text: str) -> List[Tuple[str, str]]:
        """Extract order by clauses from the query."""
        order_clauses = []
        matches = self.order_pattern.finditer(query_text)
        
        for match in matches:
            field, direction_text = match.groups()
            direction = self.ORDER_KEYWORDS.get(direction_text.lower(), 'ASC')
            order_clauses.append((field, direction))
        
        return order_clauses
    
    def _extract_limit(self, query_text: str) -> Optional[int]:
        """Extract limit from the query."""
        # Look for patterns like "top 10" or "limit 5"
        limit_pattern = re.compile(r"(?:top|limit)\s+(\d+)", re.IGNORECASE)
        match = limit_pattern.search(query_text)
        
        if match:
            return int(match.group(1))
        return None

# Example usage:
"""
from reports.nli_reporting.metadata_reader import ORMMetadataReader

# Initialize the metadata reader and NLP engine
metadata_reader = ORMMetadataReader(['contracts'])
nlp_engine = NLPEngine(metadata_reader)

# Parse some example queries
queries = [
    "show all contracts",
    "count contracts by supplier",
    "show contracts where amount is greater than 1000",
    "average delivery time by supplier",
    "top 10 suppliers by contract count order by count descending"
]

for query in queries:
    parsed = nlp_engine.parse_query(query)
    print(f"Query: {query}")
    print(f"Parsed: {parsed}")
    print()
""" 