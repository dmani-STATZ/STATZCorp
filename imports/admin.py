from django.contrib import admin
from .models import ImportSession, ImportRow, ValueTranslationMap

admin.site.register(ImportSession)
admin.site.register(ImportRow)
admin.site.register(ValueTranslationMap)
