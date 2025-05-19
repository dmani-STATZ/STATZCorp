"""
Learning Engine for NLI.

This module provides functionality to learn from query patterns and improve query understanding over time.
"""
import re
from typing import Dict, List, Optional, Tuple, Any
from django.db.models import F, Avg, Count
from django.utils import timezone
from datetime import timedelta

from ..models import QueryLog, QueryPattern, FieldMapping

class LearningEngine:
    """Engine for learning from query patterns and improving NLI capabilities."""
    
    def __init__(self):
        """Initialize the learning engine."""
        self.similarity_threshold = 0.7  # Minimum similarity score to consider queries related
    
    def log_query(self, raw_query: str, normalized_query: str, parsed_fields: Dict,
                 query_type: str, execution_time: float, was_successful: bool,
                 error_message: Optional[str] = None, result_count: int = 0,
                 user=None) -> QueryLog:
        """Log a query execution for learning."""
        # Create the query log
        query_log = QueryLog.objects.create(
            raw_query=raw_query,
            normalized_query=normalized_query,
            parsed_fields=parsed_fields,
            query_type=query_type,
            was_successful=was_successful,
            error_message=error_message,
            execution_time=execution_time,
            result_count=result_count,
            user=user
        )
        
        # Update or create query patterns
        if was_successful:
            self._update_query_patterns(query_log)
        
        return query_log
    
    def get_query_suggestions(self, partial_query: str) -> List[str]:
        """Get query suggestions based on successful past queries."""
        # Get successful queries from the last 30 days
        recent_queries = QueryLog.objects.filter(
            was_successful=True,
            timestamp__gte=timezone.now() - timedelta(days=30)
        ).order_by('-timestamp')
        
        suggestions = []
        seen = set()
        
        for log in recent_queries:
            if log.normalized_query not in seen and len(suggestions) < 5:
                if self._is_relevant_suggestion(partial_query, log.normalized_query):
                    suggestions.append(log.raw_query)
                    seen.add(log.normalized_query)
        
        return suggestions
    
    def get_field_suggestions(self, field_name: str) -> List[str]:
        """Get suggestions for field names based on successful mappings."""
        patterns = QueryPattern.objects.filter(
            success_rate__gte=0.7
        ).order_by('-usage_count')
        
        field_mappings = {}
        for pattern in patterns:
            mappings = pattern.field_mappings
            for natural_term, db_field in mappings.items():
                if db_field == field_name:
                    field_mappings[natural_term] = field_mappings.get(natural_term, 0) + 1
        
        # Return top 5 most common natural language terms for this field
        return sorted(field_mappings.keys(), key=lambda k: field_mappings[k], reverse=True)[:5]
    
    def _find_similar_queries(self, query_log: QueryLog):
        """Find and link similar queries."""
        recent_queries = QueryLog.objects.filter(
            timestamp__gte=timezone.now() - timedelta(days=30)
        ).exclude(id=query_log.id)
        
        for other_query in recent_queries:
            if self._calculate_similarity(query_log.normalized_query, other_query.normalized_query) >= self.similarity_threshold:
                query_log.similar_queries.add(other_query)
    
    def _update_query_patterns(self, query_log: QueryLog):
        """Update or create query patterns based on successful queries."""
        pattern_template = self._extract_pattern_template(query_log.normalized_query)
        
        # First try to find an exact match
        try:
            pattern = QueryPattern.objects.get(
                original_pattern=pattern_template,
                corrected_pattern=pattern_template  # Also match the corrected pattern
            )
            # Update existing pattern
            pattern.usage_count = F('usage_count') + 1
            if query_log.was_successful:
                pattern.success_count = F('success_count') + 1
            pattern.save()
            
            # Refresh from db to get updated counts
            pattern.refresh_from_db()
            pattern.update_success_rate()
            
        except QueryPattern.DoesNotExist:
            # Create new pattern
            pattern = QueryPattern.objects.create(
                original_pattern=pattern_template,
                corrected_pattern=pattern_template,
                usage_count=1,
                success_count=1 if query_log.was_successful else 0,
                success_rate=100.0 if query_log.was_successful else 0.0
            )
        except QueryPattern.MultipleObjectsReturned:
            # If multiple patterns exist, update the one with the highest success rate
            patterns = QueryPattern.objects.filter(
                original_pattern=pattern_template
            ).order_by('-success_rate', '-usage_count')
            pattern = patterns.first()
            pattern.usage_count = F('usage_count') + 1
            if query_log.was_successful:
                pattern.success_count = F('success_count') + 1
            pattern.save()
            
            # Refresh from db to get updated counts
            pattern.refresh_from_db()
            pattern.update_success_rate()
    
    def _calculate_similarity(self, query1: str, query2: str) -> float:
        """Calculate similarity score between two queries."""
        # Implement similarity calculation (e.g., using Levenshtein distance)
        # For now, using a simple word overlap metric
        words1 = set(query1.lower().split())
        words2 = set(query2.lower().split())
        
        intersection = len(words1.intersection(words2))
        union = len(words1.union(words2))
        
        return intersection / union if union > 0 else 0.0
    
    def _is_relevant_suggestion(self, partial: str, full: str) -> bool:
        """Check if a full query is a relevant suggestion for a partial query."""
        partial = partial.lower().strip()
        full = full.lower().strip()
        
        # Check if partial query is a prefix of full query
        if full.startswith(partial):
            return True
        
        # Check if all words in partial query appear in full query
        partial_words = set(partial.split())
        full_words = set(full.split())
        
        return partial_words.issubset(full_words)
    
    def _extract_pattern_template(self, query: str) -> str:
        """Extract a pattern template from a query by replacing specific values with placeholders."""
        # Replace numbers with {number}
        query = re.sub(r'\b\d+\b', '{number}', query)
        
        # Replace dates with {date}
        query = re.sub(r'\b\d{4}-\d{2}-\d{2}\b', '{date}', query)
        
        # Replace specific field values with {value}
        query = re.sub(r'(?<=is\s)[\w\s]+(?=\s|$)', '{value}', query)
        
        return query
    
    def get_improved_field_mappings(self) -> Dict[str, List[str]]:
        """Get improved field mappings based on successful query patterns."""
        successful_patterns = QueryPattern.objects.filter(
            success_rate__gte=80.0,  # Using the actual field now
            usage_count__gte=5
        ).order_by('-usage_count')
        
        field_mappings = {}
        for pattern in successful_patterns:
            for natural_term, db_field in pattern.field_mappings.items():
                if db_field not in field_mappings:
                    field_mappings[db_field] = []
                if natural_term not in field_mappings[db_field]:
                    field_mappings[db_field].append(natural_term)
        
        return field_mappings
    
    def analyze_error_patterns(self) -> Dict[str, List[Dict]]:
        """Analyze common error patterns in failed queries."""
        recent_failures = QueryLog.objects.filter(
            was_successful=False,
            timestamp__gte=timezone.now() - timedelta(days=30)
        )
        
        error_patterns = {}
        for failure in recent_failures:
            error_type = self._categorize_error(failure.error_message)
            if error_type not in error_patterns:
                error_patterns[error_type] = []
            error_patterns[error_type].append({
                'query': failure.raw_query,
                'error': failure.error_message,
                'frequency': QueryLog.objects.filter(
                    error_message=failure.error_message,
                    timestamp__gte=timezone.now() - timedelta(days=30)
                ).count()
            })
        
        return error_patterns
    
    def _categorize_error(self, error_message: str) -> str:
        """Categorize an error message into a general error type."""
        if 'field' in error_message.lower():
            return 'field_error'
        elif 'syntax' in error_message.lower():
            return 'syntax_error'
        elif 'value' in error_message.lower():
            return 'value_error'
        return 'other_error'
    
    def get_learning_stats(self) -> Dict[str, Any]:
        """Get statistics about what the system has learned."""
        stats = {
            'total_queries': QueryLog.objects.count(),
            'successful_queries': QueryLog.objects.filter(was_successful=True).count(),
            'learned_patterns': QueryPattern.objects.count(),
            'top_patterns': [],
            'field_mappings': {},
            'recent_learnings': [],
        }
        
        # Get top successful patterns
        top_patterns = QueryPattern.objects.filter(
            success_rate__gte=0.7,
            usage_count__gte=5
        ).order_by('-usage_count')[:5]
        
        for pattern in top_patterns:
            stats['top_patterns'].append({
                'pattern': pattern.pattern,
                'success_rate': pattern.success_rate,
                'usage_count': pattern.usage_count,
                'mappings': pattern.field_mappings
            })
        
        # Get most common field mappings
        recent_logs = QueryLog.objects.filter(
            was_successful=True,
            timestamp__gte=timezone.now() - timedelta(days=30)
        )
        
        field_counts = {}
        for log in recent_logs:
            for natural_term, field_name in log.parsed_fields.items():
                if field_name not in field_counts:
                    field_counts[field_name] = {}
                if natural_term not in field_counts[field_name]:
                    field_counts[field_name][natural_term] = 0
                field_counts[field_name][natural_term] += 1
        
        stats['field_mappings'] = field_counts
        
        # Get recent learnings
        recent_learnings = QueryLog.objects.filter(
            timestamp__gte=timezone.now() - timedelta(hours=24)
        ).order_by('-timestamp')[:10]
        
        for log in recent_learnings:
            stats['recent_learnings'].append({
                'query': log.raw_query,
                'success': log.was_successful,
                'fields': log.parsed_fields,
                'time': log.timestamp
            })
        
        return stats
    
    def get_field_learning_progress(self, field_name: str) -> Dict[str, Any]:
        """Get detailed learning progress for a specific field."""
        progress = {
            'field_name': field_name,
            'total_uses': 0,
            'successful_uses': 0,
            'variations': [],
            'common_patterns': [],
            'success_rate': 0.0,
        }
        
        # Get all logs where this field was used
        field_logs = QueryLog.objects.filter(
            parsed_fields__contains=field_name
        )
        
        progress['total_uses'] = field_logs.count()
        progress['successful_uses'] = field_logs.filter(was_successful=True).count()
        
        if progress['total_uses'] > 0:
            progress['success_rate'] = (progress['successful_uses'] / progress['total_uses']) * 100
        
        # Get variations used for this field
        variations = {}
        for log in field_logs:
            for natural_term, field in log.parsed_fields.items():
                if field == field_name:
                    if natural_term not in variations:
                        variations[natural_term] = {
                            'uses': 0,
                            'successful': 0
                        }
                    variations[natural_term]['uses'] += 1
                    if log.was_successful:
                        variations[natural_term]['successful'] += 1
        
        progress['variations'] = [
            {
                'term': term,
                'uses': stats['uses'],
                'successful': stats['successful'],
                'success_rate': (stats['successful'] / stats['uses']) * 100
            }
            for term, stats in variations.items()
        ]
        
        # Get common patterns using this field
        patterns = QueryPattern.objects.filter(
            field_mappings__contains=field_name
        ).order_by('-usage_count')[:5]
        
        for pattern in patterns:
            progress['common_patterns'].append({
                'pattern': pattern.pattern,
                'usage_count': pattern.usage_count,
                'success_rate': pattern.success_rate
            })
        
        return progress
    
    def get_learning_suggestions(self) -> List[Dict[str, Any]]:
        """Get suggestions for improving the system's learning."""
        suggestions = []
        
        # Find fields with low success rates
        field_stats = {}
        for log in QueryLog.objects.filter(
            timestamp__gte=timezone.now() - timedelta(days=30)
        ):
            for field in log.parsed_fields.values():
                if field not in field_stats:
                    field_stats[field] = {'total': 0, 'success': 0}
                field_stats[field]['total'] += 1
                if log.was_successful:
                    field_stats[field]['success'] += 1
        
        for field, stats in field_stats.items():
            if stats['total'] >= 5:  # Only consider fields with enough data
                success_rate = (stats['success'] / stats['total']) * 100
                if success_rate < 70:
                    suggestions.append({
                        'type': 'low_success_rate',
                        'field': field,
                        'success_rate': success_rate,
                        'total_uses': stats['total'],
                        'message': f"Field '{field}' has a low success rate ({success_rate:.1f}%). Consider adding more variations."
                    })
        
        # Find common error patterns
        error_patterns = self.analyze_error_patterns()
        for error_type, errors in error_patterns.items():
            if len(errors) >= 3:  # If we see the same error multiple times
                suggestions.append({
                    'type': 'common_error',
                    'error_type': error_type,
                    'count': len(errors),
                    'examples': errors[:3],
                    'message': f"Found {len(errors)} similar {error_type} errors. Consider improving handling."
                })
        
        return suggestions
    
    def process_feedback(self, query_log: QueryLog, feedback: str) -> None:
        """Process user feedback about incorrect results."""
        # Extract key information from feedback
        feedback_type = self._categorize_feedback(feedback)
        
        if feedback_type == 'date_filter':
            # Update field mappings for date fields
            self._update_date_field_handling(query_log)
        elif feedback_type == 'numeric_filter':
            # Update numeric field handling
            self._update_numeric_field_handling(query_log)
        elif feedback_type == 'field_mapping':
            # Update field name mappings
            self._update_field_mappings(query_log)
        
        # Store the feedback for future analysis
        query_log.user_feedback = feedback
        query_log.save()

    def process_corrections(self, query_log: QueryLog) -> None:
        """Process corrections made to a query through the training interface."""
        if not query_log.corrected_query or not query_log.field_mappings:
            return
        
        # Update field mappings based on corrections
        self._learn_from_corrections(query_log)
        
        # Update query patterns
        self._update_query_patterns(query_log)
        
        # Mark query as processed
        query_log.corrections_processed = True
        query_log.save()

    def process_correct_query(self, query_log: QueryLog) -> None:
        """Process a query that was marked as correct."""
        # Learn from the successful query
        self._learn_from_success(query_log)
        
        # Update success metrics
        self._update_success_metrics(query_log)

    def _learn_from_corrections(self, query_log: QueryLog) -> None:
        """Learn from manual corrections made to a query."""
        # Get the original and corrected queries
        original = query_log.normalized_query
        corrected = query_log.corrected_query
        
        # Learn field mappings
        for natural_term, db_field in query_log.field_mappings.items():
            self._add_field_mapping(natural_term, db_field)
        
        # Learn query patterns
        if corrected:
            self._add_query_pattern(original, corrected)

    def _add_field_mapping(self, natural_term: str, db_field: str) -> None:
        """Add or update a field mapping."""
        try:
            # Try to find existing mapping
            mapping = FieldMapping.objects.get(natural_term=natural_term)
            # Update confidence if this mapping matches
            if mapping.db_field == db_field:
                mapping.confidence += 0.1
                mapping.usage_count += 1
            else:
                # Different mapping exists, adjust confidence based on usage
                if mapping.usage_count > 10 and mapping.confidence > 0.8:
                    # Keep existing mapping if it's well established
                    return
                mapping.db_field = db_field
                mapping.confidence = 0.6  # Reset confidence for new mapping
            mapping.save()
        except FieldMapping.DoesNotExist:
            # Create new mapping
            FieldMapping.objects.create(
                natural_term=natural_term,
                db_field=db_field,
                confidence=0.7,
                usage_count=1
            )

    def _add_query_pattern(self, original: str, corrected: str) -> None:
        """Add or update a query pattern."""
        try:
            # Try to find similar pattern
            pattern = QueryPattern.objects.get(
                original_pattern__iexact=original
            )
            # Update if found
            pattern.corrected_pattern = corrected
            pattern.usage_count += 1
            pattern.save()
        except QueryPattern.DoesNotExist:
            # Create new pattern
            QueryPattern.objects.create(
                original_pattern=original,
                corrected_pattern=corrected,
                usage_count=1
            )

    def _update_success_metrics(self, query_log: QueryLog) -> None:
        """Update success metrics for query patterns."""
        # Update success count for similar queries
        similar_patterns = QueryPattern.objects.filter(
            original_pattern__icontains=query_log.normalized_query
        )
        for pattern in similar_patterns:
            pattern.success_count += 1
            pattern.save()

    def _learn_from_success(self, query_log: QueryLog) -> None:
        """Learn from a successful query."""
        # Increase confidence in field mappings used
        for field in query_log.parsed_fields:
            try:
                mapping = FieldMapping.objects.get(db_field=field)
                mapping.confidence = min(1.0, mapping.confidence + 0.05)
                mapping.usage_count += 1
                mapping.save()
            except FieldMapping.DoesNotExist:
                continue
        
        # Add query pattern if it doesn't exist
        self._add_query_pattern(
            query_log.normalized_query,
            query_log.normalized_query  # Same since it was successful
        )

    def _categorize_feedback(self, feedback: str) -> str:
        """Categorize the type of feedback."""
        feedback = feedback.lower()
        if any(word in feedback for word in ['date', 'year', 'month', 'day']):
            return 'date_filter'
        elif any(word in feedback for word in ['number', 'amount', 'value', 'greater', 'less']):
            return 'numeric_filter'
        return 'field_mapping'

    def _update_date_field_handling(self, query_log: QueryLog) -> None:
        """Update how date fields are handled based on feedback."""
        pattern = QueryPattern.objects.filter(
            pattern=self._extract_pattern_template(query_log.normalized_query)
        ).first()
        
        if pattern:
            # Update the pattern to handle date ranges better
            pattern.field_mappings.update({
                'in year': 'year_equals',
                'before year': 'year_lt',
                'after year': 'year_gt',
                'during': 'date_range'
            })
            pattern.success_rate = (pattern.success_rate * 0.8)  # Reduce success rate
            pattern.save()

    def _update_numeric_field_handling(self, query_log: QueryLog) -> None:
        """Update how numeric fields are handled based on feedback."""
        pattern = QueryPattern.objects.filter(
            pattern=self._extract_pattern_template(query_log.normalized_query)
        ).first()
        
        if pattern:
            # Update the pattern to handle numeric comparisons better
            pattern.field_mappings.update({
                'greater than': 'gt',
                'less than': 'lt',
                'equal to': 'exact',
                'between': 'range'
            })
            pattern.success_rate = (pattern.success_rate * 0.8)  # Reduce success rate
            pattern.save()

    def _update_field_mappings(self, query_log: QueryLog) -> None:
        """Update field name mappings based on feedback."""
        # Implement the logic to update field mappings based on feedback
        pass
    
    def _update_pattern_success_rate(self, query_log: QueryLog) -> None:
        """Update the success rate of query patterns based on feedback."""
        # Implement the logic to update the success rate of query patterns based on feedback
        pass

    def _generate_corrected_pattern(self, query_log: QueryLog, feedback: str) -> None:
        """Generate a corrected query pattern based on feedback."""
        # Create a new pattern with corrections
        corrected_pattern = self._extract_pattern_template(query_log.normalized_query)
        
        # Add specific handling for date queries
        if 'date' in feedback.lower() or 'year' in feedback.lower():
            corrected_pattern = corrected_pattern.replace(
                '{date}',
                'YEAR({field}) = {year}'
            )
        
        # Create new pattern with corrections
        QueryPattern.objects.create(
            pattern=corrected_pattern,
            field_mappings=query_log.parsed_fields,
            success_rate=100.0,
            usage_count=1
        )

    def process_sql_verification(self, query_log: QueryLog, verified_sql: str) -> Dict[str, Any]:
        """Process SQL verification for a query.
        
        Args:
            query_log: The QueryLog instance being verified
            verified_sql: The verified SQL query from SSMS
            
        Returns:
            Dict containing success status and any additional data
        """
        try:
            # Update the query log with verified SQL
            query_log.verified_sql = verified_sql
            query_log.sql_verified = True
            query_log.sql_verification_date = timezone.now()
            
            # Try to generate ORM translation
            orm_translation = self._generate_orm_translation(verified_sql)
            query_log.orm_translation = orm_translation
            
            # Learn from the verified SQL
            self._learn_from_verified_sql(query_log, verified_sql)
            
            # Update success metrics
            self._update_success_metrics(query_log)
            
            # Find and update similar queries
            self._find_similar_queries(query_log)
            
            # Save all changes
            query_log.save()
            
            return {
                'success': True,
                'message': 'SQL verification saved and processed successfully',
                'orm_translation': orm_translation
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def _learn_from_verified_sql(self, query_log: QueryLog, verified_sql: str) -> None:
        """Learn patterns from verified SQL to improve future query processing.
        
        This method analyzes the verified SQL to:
        1. Extract and learn field mappings
        2. Learn query patterns
        3. Update the query pattern database
        4. Improve field name normalization
        """
        try:
            # Extract table and field names from SQL
            tables = re.findall(r'FROM\s+(\w+)|JOIN\s+(\w+)', verified_sql, re.IGNORECASE)
            fields = re.findall(r'SELECT\s+(.+?)\s+FROM', verified_sql, re.IGNORECASE)
            conditions = re.findall(r'WHERE\s+(.+?)(?:\s+(?:GROUP BY|ORDER BY|LIMIT|$))', verified_sql, re.IGNORECASE)
            
            # Learn field mappings
            if fields:
                field_list = fields[0].split(',')
                for field in field_list:
                    field = field.strip()
                    # Handle aliased fields
                    if ' AS ' in field.upper():
                        db_field, natural_term = field.split(' AS ', 1)
                        self._add_field_mapping(natural_term.strip(), db_field.strip())
            
            # Learn from WHERE conditions
            if conditions:
                for condition in conditions[0].split('AND'):
                    # Extract field names and operators
                    match = re.search(r'(\w+)\s*(=|>|<|>=|<=|LIKE|IN)', condition.strip(), re.IGNORECASE)
                    if match:
                        field_name = match.group(1)
                        operator = match.group(2)
                        # Store the field name and operator pattern
                        self._add_query_pattern(
                            f"{field_name} {operator}",
                            f"{field_name}{self._convert_operator(operator)}"
                        )
            
            # Create a new pattern with the full query structure
            pattern_template = self._extract_pattern_template(verified_sql)
            QueryPattern.objects.create(
                original_pattern=query_log.normalized_query,
                corrected_pattern=pattern_template,
                usage_count=1,
                success_count=1,
                success_rate=100.0
            )
            
        except Exception as e:
            # Log the error but don't raise it to avoid breaking the verification process
            print(f"Error learning from verified SQL: {str(e)}")
    
    def _generate_orm_translation(self, sql_query: str) -> str:
        """Translate SQL to Django ORM.
        
        This method analyzes the SQL query and attempts to generate an equivalent Django ORM query.
        It handles common SQL patterns like:
        - SELECT with field aliases
        - WHERE clauses with multiple conditions
        - ORDER BY
        """
        try:
            # Remove newlines and extra spaces
            sql_query = ' '.join(sql_query.split())
            
            # Initialize the ORM translation
            orm_parts = []
            imports = ['from django.db.models import Q']
            
            # Extract the base model from FROM clause
            match = re.search(r'FROM\s+(\w+)', sql_query, re.IGNORECASE)
            if not match:
                return "# Error: Could not find FROM clause"
            
            model_name = match.group(1)
            orm_parts.append(f"{model_name}.objects")
            
            # Handle SELECT fields with aliases
            select_match = re.search(r'SELECT\s+(.+?)\s+FROM', sql_query, re.IGNORECASE)
            if select_match:
                fields = select_match.group(1).strip()
                if fields != '*':
                    field_list = []
                    for field in fields.split(','):
                        field = field.strip()
                        # Handle field AS [Alias] pattern
                        as_match = re.search(r'(\w+)\s+AS\s+\[([^\]]+)\]', field, re.IGNORECASE)
                        if as_match:
                            db_field = as_match.group(1).strip()
                            field_list.append(db_field)
                        else:
                            field_list.append(field)
                    
                    if field_list:
                        orm_parts.append(f"values({', '.join(repr(f) for f in field_list)})")
            
            # Handle WHERE conditions
            where_match = re.search(r'WHERE\s+(.+?)(?:\s+(?:GROUP BY|ORDER BY|LIMIT|$))', sql_query, re.IGNORECASE)
            if where_match:
                conditions = where_match.group(1).strip('()')  # Remove outer parentheses
                q_objects = []
                
                # Split conditions by AND/OR
                for condition in re.split(r'\s+AND\s+', conditions, flags=re.IGNORECASE):
                    # Parse basic comparisons
                    comp_match = re.search(r'(\w+)\s*(=|>|<|>=|<=|!=|LIKE|IN|IS NULL|IS NOT NULL)\s*([^AND|OR]*)', condition.strip(), re.IGNORECASE)
                    if comp_match:
                        field, op, value = comp_match.groups()
                        field = field.strip()
                        op = op.strip().upper()
                        value = value.strip() if value else None
                        
                        # Try to convert value to appropriate type
                        if value:
                            value = value.strip("'")  # Remove quotes
                            try:
                                value = int(value)
                            except ValueError:
                                try:
                                    value = float(value)
                                except ValueError:
                                    pass  # Keep as string
                        
                        # Build Q object condition
                        if op == 'LIKE':
                            q_objects.append(f"Q({field}__icontains={repr(value.strip('%'))})")
                        elif op == 'IN':
                            q_objects.append(f"Q({field}__in={value})")
                        elif op in ('IS NULL', 'IS NOT NULL'):
                            q_objects.append(f"Q({field}__isnull={'True' if op == 'IS NULL' else 'False'})")
                        else:
                            lookup = {
                                '=': '',
                                '>': '__gt',
                                '<': '__lt',
                                '>=': '__gte',
                                '<=': '__lte',
                                '!=': '__ne'
                            }.get(op, '')
                            q_objects.append(f"Q({field}{lookup}={repr(value)})")
                
                if q_objects:
                    # Combine Q objects with AND
                    orm_parts.append(f"filter({' & '.join(q_objects)})")
            
            # Handle ORDER BY
            order_match = re.search(r'ORDER BY\s+(.+?)(?:\s+LIMIT|$)', sql_query, re.IGNORECASE)
            if order_match:
                order_fields = []
                for field in order_match.group(1).split(','):
                    field = field.strip()
                    if ' DESC' in field.upper():
                        field = f"-{field.replace(' DESC', '').strip()}"
                    else:
                        field = field.replace(' ASC', '').strip()
                    order_fields.append(field)
                orm_parts.append(f"order_by({', '.join(repr(f) for f in order_fields)})")
            
            # Handle LIMIT
            limit_match = re.search(r'LIMIT\s+(\d+)', sql_query, re.IGNORECASE)
            if limit_match:
                orm_parts.append(f"[:{limit_match.group(1)}]")
            
            # Combine all parts
            orm_query = '.'.join(orm_parts)
            
            # Return the complete translation with proper newlines
            return '\n'.join([
                *imports,
                "",
                f"queryset = {orm_query}"
            ])
            
        except Exception as e:
            return f"# Error generating ORM translation: {str(e)}\n{sql_query}"
    
    def _convert_operator(self, sql_op: str) -> str:
        """Convert SQL operators to Django ORM field lookups."""
        op_map = {
            '=': '',
            '>': '__gt',
            '<': '__lt',
            '>=': '__gte',
            '<=': '__lte',
            '!=': '__ne',
            'LIKE': '__icontains',
            'IN': '__in'
        }
        return op_map.get(sql_op.upper(), '') 