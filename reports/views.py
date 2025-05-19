"""
Views for the reports app.

This module provides views for handling natural language queries and displaying results.
"""
import logging
import time
import json
from typing import Dict, Any
from datetime import datetime
from django.shortcuts import render
from django.http import JsonResponse, HttpResponse
from django.views.generic import TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.paginator import Paginator
from django.core.exceptions import FieldDoesNotExist
import openpyxl
from openpyxl.styles import Font, PatternFill
from io import BytesIO
from django.views.generic import View
from django.db.models import Count
from django.utils import timezone
import re

from .nli_reporting.metadata_reader import ORMMetadataReader
from .nli_reporting.nlp_engine import NLPEngine
from .nli_reporting.query_builder import QueryBuilder
from .nli_reporting.learning_engine import LearningEngine
from .models import QueryLog

logger = logging.getLogger(__name__)

class NLQueryView(LoginRequiredMixin, TemplateView):
    """View for handling natural language queries."""
    
    template_name = 'reports/nli/query.html'
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Initialize components
        self.metadata_reader = ORMMetadataReader(['contracts'])
        self.nlp_engine = NLPEngine(self.metadata_reader)
        self.query_builder = QueryBuilder(self.metadata_reader)
        self.learning_engine = LearningEngine()
        
        # Connect NLP engine to query builder for field name normalization
        self.query_builder.set_nlp_engine(self.nlp_engine)
    
    def get_context_data(self, **kwargs) -> Dict[str, Any]:
        """Get context data for rendering the template."""
        context = super().get_context_data(**kwargs)
        
        # Add available models and fields to context
        context['models'] = {}
        for model_key, model_metadata in self.metadata_reader.models.items():
            app_label, model_name = model_key.split('.')
            if app_label not in context['models']:
                context['models'][app_label] = {}
            
            # Get field mappings for this model
            field_variations = {}
            for natural_name, field_name in self.nlp_engine.FIELD_MAPPINGS.items():
                if field_name in model_metadata.fields:
                    if field_name not in field_variations:
                        field_variations[field_name] = []
                    field_variations[field_name].append(natural_name)
            
            context['models'][app_label][model_name] = {
                'fields': model_metadata.fields,
                'relationships': model_metadata.relationships,
                'field_variations': field_variations,  # Add field variations to context
            }
        
        # Add field mappings from learning engine
        context['field_mappings'] = self.learning_engine.get_improved_field_mappings()
        
        # Add common error patterns
        context['error_patterns'] = self.learning_engine.analyze_error_patterns()
        
        return context
    
    def post(self, request, *args, **kwargs):
        """Handle POST requests with natural language queries."""
        # Check if this is a JSON request
        if request.headers.get('Content-Type') == 'application/json':
            try:
                data = json.loads(request.body)
                feedback = data.get('feedback', '')
                query_id = data.get('query_id')
                if feedback and query_id:
                    return self._handle_feedback(request, query_id, feedback)
            except json.JSONDecodeError:
                return JsonResponse({'success': False, 'error': 'Invalid JSON data'}, status=400)
        
        # Handle regular form data
        query_text = request.POST.get('query', '')
        page_number = request.POST.get('page', 1)
        export = request.POST.get('export', '')
        
        # Regular query processing
        logger.debug(f"Processing query: {query_text}")
        start_time = time.time()
        error_message = None
        result_count = 0
        
        try:
            # Parse the query
            parsed_query = self.nlp_engine.parse_query(query_text)
            logger.debug(f"Parsed query: {parsed_query}")
            
            # Build and execute the query
            queryset, query_context = self.query_builder.build_query(parsed_query)
            
            # If exporting to Excel, return Excel file
            if export == 'excel':
                return self._export_to_excel(queryset, query_text)
            
            # Paginate results for normal view
            paginator = Paginator(queryset, 10)  # Show 10 items per page
            page_obj = paginator.get_page(page_number)
            
            # Convert queryset to list for serialization
            results = []
            for obj in page_obj:
                if isinstance(obj, dict):
                    results.append(obj)
                else:
                    # Convert model instance to dict
                    results.append({
                        field.name: getattr(obj, field.name)
                        for field in obj._meta.fields
                    })
            
            result_count = paginator.count
            was_successful = True
            
            # Prepare the response
            response_data = {
                'success': True,
                'results': results,
                'total_pages': paginator.num_pages,
                'current_page': page_obj.number,
                'has_next': page_obj.has_next(),
                'has_previous': page_obj.has_previous(),
                'total_count': paginator.count,
                'query_context': {
                    'type': parsed_query.query_type.name,  # Convert enum to string
                    'fields': parsed_query.fields,
                    'group_by': parsed_query.group_by,
                    'aggregations': [
                        (agg_type.name, field) for agg_type, field in (parsed_query.aggregations or [])
                    ],
                },
            }
            
            # Log the query for learning
            execution_time = time.time() - start_time
            query_log = self.learning_engine.log_query(
                raw_query=query_text,
                normalized_query=query_text.lower().strip(),
                parsed_fields={
                    field: field for field in (parsed_query.fields if 'parsed_query' in locals() else [])
                },
                query_type=parsed_query.query_type.name if 'parsed_query' in locals() else 'UNKNOWN',
                execution_time=execution_time,
                was_successful=was_successful,
                error_message=error_message,
                result_count=result_count,
                user=request.user
            )
            
            # Add query_id to response for feedback reference
            response_data['query_id'] = query_log.id
            
            # Add query suggestions
            response_data['suggestions'] = self.learning_engine.get_query_suggestions(query_text)
            
        except FieldDoesNotExist as e:
            logger.warning(f"Invalid field in query: {str(e)}")
            error_message = f"Invalid field: {str(e)}"
            response_data = {
                'success': False,
                'error': error_message,
            }
            was_successful = False
            
        except ValueError as e:
            logger.warning(f"Value error in query: {str(e)}")
            error_message = str(e)
            response_data = {
                'success': False,
                'error': error_message,
            }
            was_successful = False
            
        except Exception as e:
            logger.error(f"Error processing query: {str(e)}", exc_info=True)
            error_message = f"An error occurred: {str(e)}"
            response_data = {
                'success': False,
                'error': error_message,
            }
            was_successful = False
        
        finally:
            # Log the query for learning if not already logged
            if 'query_log' not in locals():
                execution_time = time.time() - start_time
                self.learning_engine.log_query(
                    raw_query=query_text,
                    normalized_query=query_text.lower().strip(),
                    parsed_fields={},
                    query_type='UNKNOWN',
                    execution_time=execution_time,
                    was_successful=was_successful,
                    error_message=error_message,
                    result_count=result_count,
                    user=request.user
                )
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse(response_data)
        else:
            context = self.get_context_data()
            context.update(response_data)
            return render(request, self.template_name, context)

    def _handle_feedback(self, request, query_id, feedback):
        """Handle user feedback about query results."""
        try:
            query_log = QueryLog.objects.get(id=query_id)
            
            # Update the query log with feedback
            query_log.was_helpful = False
            query_log.user_feedback = feedback
            query_log.save()
            
            # Let the learning engine process the feedback
            self.learning_engine.process_feedback(query_log, feedback)
            
            # Return only serializable data
            return JsonResponse({
                'success': True,
                'message': 'Thank you for your feedback. The system will learn from this.',
                'query_id': query_log.id,
                'feedback_saved': True,
                'timestamp': datetime.now().isoformat()
            })
            
        except QueryLog.DoesNotExist:
            return JsonResponse({
                'success': False,
                'error': 'Query log not found',
                'query_id': query_id
            }, status=404)
        except Exception as e:
            logger.error(f"Error processing feedback: {str(e)}", exc_info=True)
            return JsonResponse({
                'success': False,
                'error': 'An error occurred while processing your feedback',
                'details': str(e)
            }, status=500)

    def _export_to_excel(self, queryset, query_text):
        """Export queryset to Excel file."""
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Query Results"
        
        # Add query info
        ws['A1'] = "Query:"
        ws['B1'] = query_text
        ws['A1'].font = Font(bold=True)
        ws['A2'] = "Generated:"
        ws['B2'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ws['A2'].font = Font(bold=True)
        
        # Get headers
        if queryset:
            first_item = queryset[0]
            if isinstance(first_item, dict):
                headers = list(first_item.keys())
            else:
                headers = [field.name for field in first_item._meta.fields]
            
            # Write headers
            for col, header in enumerate(headers, 1):
                cell = ws.cell(row=4, column=col, value=header)
                cell.font = Font(bold=True)
                cell.fill = PatternFill(start_color="CCCCCC", end_color="CCCCCC", fill_type="solid")
            
            # Write data
            for row, obj in enumerate(queryset, 5):
                for col, header in enumerate(headers, 1):
                    if isinstance(obj, dict):
                        value = obj.get(header)
                    else:
                        value = getattr(obj, header)
                    ws.cell(row=row, column=col, value=value)
        
        # Auto-adjust column widths
        for column in ws.columns:
            max_length = 0
            column = [cell for cell in column]
            for cell in column:
                try:
                    if len(str(cell.value)) > max_length:
                        max_length = len(str(cell.value))
                except:
                    pass
            adjusted_width = (max_length + 2)
            ws.column_dimensions[column[0].column_letter].width = adjusted_width
        
        # Save to buffer and return
        buffer = BytesIO()
        wb.save(buffer)
        buffer.seek(0)
        
        response = HttpResponse(
            buffer.getvalue(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        response['Content-Disposition'] = f'attachment; filename=query_results_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx'
        return response

class NLITrainingView(LoginRequiredMixin, TemplateView):
    """View for the NLI training interface."""
    
    template_name = 'reports/nli/training.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        return context

class NLITrainingAPIView(LoginRequiredMixin, View):
    """API view for the NLI training interface."""
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.learning_engine = LearningEngine()
    
    def get(self, request, *args, **kwargs):
        """Handle GET requests."""
        action = kwargs.get('action')
        query_id = kwargs.get('query_id')
        
        if action == 'queries':
            return JsonResponse(self._get_queries())
        elif action == 'stats':
            return JsonResponse(self._get_stats())
        elif action == 'query' and query_id:
            return JsonResponse(self._get_query_details(query_id))
        
        return JsonResponse({'error': 'Invalid action'}, status=400)
    
    def post(self, request, *args, **kwargs):
        """Handle POST requests."""
        action = kwargs.get('action')
        query_id = kwargs.get('query_id')
        
        if action == 'update' and query_id:
            return self._update_query(request, query_id)
        elif action == 'mark-correct' and query_id:
            return self._mark_query_correct(query_id)
        elif action == 'verify-sql' and query_id:
            return self._verify_sql(request, query_id)
        elif action == 'delete-all':
            return self._delete_all_queries(request)
        
        return JsonResponse({'error': 'Invalid action'}, status=400)

    def _delete_all_queries(self, request):
        """Delete all query logs."""
        try:
            # Delete all QueryLog records
            QueryLog.objects.all().delete()
            return JsonResponse({'success': True, 'message': 'All queries deleted successfully'})
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': f'Failed to delete queries: {str(e)}'
            }, status=500)

    def _get_queries(self):
        """Get list of recent queries."""
        queries = QueryLog.objects.all().order_by('-timestamp')[:50]
        return {
            'success': True,
            'queries': [{
                'id': q.id,
                'raw_query': q.raw_query,
                'normalized_query': q.normalized_query,
                'parsed_fields': q.parsed_fields,
                'query_type': q.query_type,
                'was_successful': q.was_successful,
                'error_message': q.error_message,
                'timestamp': q.timestamp.isoformat(),
                'status': 'success' if q.was_successful else 'error'
            } for q in queries]
        }
    
    def _get_stats(self):
        """Get learning statistics."""
        total_queries = QueryLog.objects.count()
        successful_queries = QueryLog.objects.filter(was_successful=True).count()
        success_rate = (successful_queries / total_queries * 100) if total_queries > 0 else 0
        
        # Get common errors
        error_patterns = QueryLog.objects.filter(
            was_successful=False,
            error_message__isnull=False
        ).values('error_message').annotate(
            count=Count('id')
        ).order_by('-count')[:5]
        
        # Get learned field mappings
        field_mappings = self.learning_engine.get_improved_field_mappings()
        
        return {
            'success_rate': round(success_rate, 2),
            'total_queries': total_queries,
            'common_errors': [
                f"{error['error_message']} ({error['count']} times)"
                for error in error_patterns
            ],
            'field_mappings': field_mappings
        }
    
    def _get_query_details(self, query_id):
        """Get details for a specific query."""
        try:
            query = QueryLog.objects.get(id=query_id)
            return {
                'raw_query': query.raw_query,
                'normalized_query': query.normalized_query,
                'parsed_fields': query.parsed_fields,
                'query_type': query.query_type,
                'was_successful': query.was_successful,
                'error_message': query.error_message,
                'corrected_query': query.corrected_query,
                'field_mappings': query.field_mappings,
                'notes': query.notes,
                'generated_sql': query.generated_sql,
                'verified_sql': query.verified_sql,
                'sql_verified': query.sql_verified,
                'orm_translation': query.orm_translation
            }
        except QueryLog.DoesNotExist:
            return {'error': 'Query not found'}
    
    def _update_query(self, request, query_id):
        """Update a query with corrections and field mappings."""
        try:
            query = QueryLog.objects.get(id=query_id)
            
            # Update query with corrections
            query.corrected_query = request.POST.get('corrected_query', '')
            query.field_mappings = json.loads(request.POST.get('field_mappings', '{}'))
            query.notes = request.POST.get('notes', '')
            query.save()
            
            # Let the learning engine process the corrections
            self.learning_engine.process_corrections(query)
            
            return JsonResponse({'success': True})
            
        except QueryLog.DoesNotExist:
            return JsonResponse({'error': 'Query not found'}, status=404)
        except json.JSONDecodeError:
            return JsonResponse({'error': 'Invalid field mappings format'}, status=400)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)
    
    def _mark_query_correct(self, query_id):
        """Mark a query as correct."""
        try:
            query = QueryLog.objects.get(id=query_id)
            query.was_successful = True
            query.save()
            
            # Let the learning engine know this query was actually correct
            self.learning_engine.process_correct_query(query)
            
            return JsonResponse({'success': True})
            
        except QueryLog.DoesNotExist:
            return JsonResponse({'error': 'Query not found'}, status=404)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)

    def _verify_sql(self, request, query_id):
        try:
            data = json.loads(request.body)
            query = QueryLog.objects.get(id=query_id)
            verified_sql = data.get('verified_sql')
            
            if not verified_sql:
                return JsonResponse({
                    'success': False,
                    'error': 'No SQL provided'
                }, status=400)
            
            # Let the learning engine process the verification
            result = self.learning_engine.process_sql_verification(query, verified_sql)
            
            if result['success']:
                return JsonResponse({
                    'success': True,
                    'message': result.get('message', 'SQL verification saved successfully'),
                    'orm_translation': result.get('orm_translation', '')
                })
            else:
                return JsonResponse({
                    'success': False,
                    'error': result.get('error', 'Failed to verify SQL')
                }, status=500)
            
        except QueryLog.DoesNotExist:
            return JsonResponse({'error': 'Query not found'}, status=404)
        except json.JSONDecodeError:
            return JsonResponse({'error': 'Invalid JSON data'}, status=400)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)

    def _translate_sql_to_orm(self, sql):
        """
        Translate SQL to Django ORM.
        This is a complex task that will need to be implemented based on your specific needs.
        """
        # This is a placeholder - we'll need to implement the actual translation logic
        # based on your specific SQL patterns and needs
        return "# SQL to ORM translation will be implemented here"
