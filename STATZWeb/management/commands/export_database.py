from django.core.management.base import BaseCommand
from django.apps import apps
from django.conf import settings
import os
import csv
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Export all database tables to CSV files'

    def add_arguments(self, parser):
        parser.add_argument(
            '--output-dir',
            type=str,
            help='Directory to store CSV files (default: exports/database_dump/YYYY-MM-DD_HH-MM-SS)',
        )

    def handle(self, *args, **options):
        # Create timestamp for the export directory
        timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        
        # Set up the export directory
        base_dir = options.get('output_dir') or os.path.join(settings.MEDIA_ROOT, 'exports', 'database_dump', timestamp)
        os.makedirs(base_dir, exist_ok=True)
        
        self.stdout.write(f"Exporting database to: {base_dir}")

        # Get all models from installed apps
        for app_config in apps.get_app_configs():
            # Skip Django's built-in apps
            if not app_config.name.startswith('django.'):
                app_models = app_config.get_models()
                
                # Create app directory
                app_dir = os.path.join(base_dir, app_config.label)
                os.makedirs(app_dir, exist_ok=True)
                
                for model in app_models:
                    try:
                        model_name = model._meta.model_name
                        self.stdout.write(f"Exporting {app_config.label}.{model_name}...")
                        
                        # Get all fields for the model
                        fields = [field.name for field in model._meta.fields]
                        
                        # Create CSV file for the model
                        csv_path = os.path.join(app_dir, f"{model_name}.csv")
                        
                        with open(csv_path, 'w', newline='', encoding='utf-8') as csvfile:
                            writer = csv.writer(csvfile)
                            
                            # Write header
                            writer.writerow(fields)
                            
                            # Write data in batches of 1000
                            queryset = model.objects.all()
                            batch_size = 1000
                            
                            for i in range(0, queryset.count(), batch_size):
                                batch = queryset[i:i + batch_size]
                                for obj in batch:
                                    row = []
                                    for field in fields:
                                        try:
                                            value = getattr(obj, field)
                                            # Convert datetime objects to string
                                            if isinstance(value, datetime):
                                                value = value.isoformat()
                                            row.append(value)
                                        except Exception as e:
                                            logger.error(f"Error getting {field} for {model_name}: {str(e)}")
                                            row.append(None)
                                    writer.writerow(row)
                                
                                self.stdout.write(f"  Exported {i + len(batch)} records...")
                        
                        self.stdout.write(self.style.SUCCESS(f"Successfully exported {app_config.label}.{model_name}"))
                    
                    except Exception as e:
                        self.stdout.write(
                            self.style.ERROR(f"Failed to export {app_config.label}.{model_name}: {str(e)}")
                        )
                        continue

        self.stdout.write(self.style.SUCCESS(f"Database export completed. Files saved in: {base_dir}")) 