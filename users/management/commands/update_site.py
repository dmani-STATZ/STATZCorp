from django.core.management.base import BaseCommand
from django.contrib.sites.models import Site

class Command(BaseCommand):
    help = 'Updates the default site configuration'

    def handle(self, *args, **options):
        site = Site.objects.get_current()
        site.domain = 'localhost:8000'
        site.name = 'STATZ Corp Local'
        site.save()
        
        self.stdout.write(
            self.style.SUCCESS(f'Successfully updated site: {site.name} ({site.domain})')
        ) 