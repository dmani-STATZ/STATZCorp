from django.core.management.commands.runserver import Command as RunserverCommand
import os
from dotenv import load_dotenv

class Command(RunserverCommand):
    def run_from_argv(self, argv):
        load_dotenv()
        os.environ.setdefault('DJANGO_SETTINGS_MODULE', os.getenv('DJANGO_SETTINGS_MODULE'))
        print(f"DJANGO_SETTINGS_MODULE: {os.getenv('DJANGO_SETTINGS_MODULE')}")
        super().run_from_argv(argv)
