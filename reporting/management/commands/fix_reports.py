from django.core.management.base import BaseCommand
import json

class Command(BaseCommand):
    help = 'Fix malformed report data in the database'

    def handle(self, *args, **options):
        from reporting.models import SavedReport
        
        reports = SavedReport.objects.all()
        fixed_count = 0
        
        for report in reports:
            try:
                # Fix selected_tables
                if isinstance(report.selected_tables, str):
                    report.selected_tables = json.loads(report.selected_tables)
                if not isinstance(report.selected_tables, list):
                    report.selected_tables = list(report.selected_tables)
                
                # Fix selected_fields
                if isinstance(report.selected_fields, str):
                    report.selected_fields = json.loads(report.selected_fields)
                if not isinstance(report.selected_fields, dict):
                    # Try to convert to proper format
                    fixed_fields = {}
                    if isinstance(report.selected_fields, list):
                        # If it's a list of "table.field", convert to proper structure
                        for field in report.selected_fields:
                            if '.' in field:
                                table, field_name = field.split('.')
                                if table not in fixed_fields:
                                    fixed_fields[table] = []
                                fixed_fields[table].append(field_name)
                    report.selected_fields = fixed_fields
                
                # Fix filters
                if isinstance(report.filters, str):
                    report.filters = json.loads(report.filters)
                if not isinstance(report.filters, list):
                    report.filters = []
                
                # Validate and fix each filter
                fixed_filters = []
                for filter_item in report.filters:
                    if isinstance(filter_item, dict) and all(k in filter_item for k in ['table', 'field', 'operator', 'value']):
                        fixed_filters.append({
                            'table': str(filter_item['table']),
                            'field': str(filter_item['field']),
                            'operator': str(filter_item['operator']),
                            'value': filter_item['value']
                        })
                report.filters = fixed_filters
                
                report.save()
                fixed_count += 1
                self.stdout.write(self.style.SUCCESS(f'Successfully fixed report {report.id}'))
                
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'Error fixing report {report.id}: {str(e)}'))
                
        self.stdout.write(self.style.SUCCESS(f'Fixed {fixed_count} reports')) 