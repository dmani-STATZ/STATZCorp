from django.shortcuts import render
from django.contrib.auth.decorators import login_required

# Import views from modular structure
from .views.processing_views import process_contract_form
from .views.matching_views import match_buyer, match_supplier, match_nsn
from .views.api_views import (
    save_and_return,
    cancel_process_contract,
    delete_processing_clin
)

# Make views available at package level
__all__ = [
    'process_contract_form',
    'match_buyer',
    'match_supplier',
    'match_nsn',
    'save_and_return',
    'cancel_process_contract',
    'delete_processing_clin'
]
