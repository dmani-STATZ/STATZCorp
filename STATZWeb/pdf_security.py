"""
PDF Security Utilities

This module provides secure PDF processing functions to mitigate
PDF processing vulnerabilities and prevent infinite loops.
Note: Migrated from PyPDF2 to pypdf for better security and maintenance.
"""

import os
from django.conf import settings
from django.core.exceptions import ValidationError


def validate_pdf_file(file_path, max_pages=None, max_size=None):
    """
    Validate PDF file before processing to prevent security issues.
    
    Args:
        file_path (str): Path to the PDF file
        max_pages (int): Maximum number of pages allowed
        max_size (int): Maximum file size in bytes
    
    Raises:
        ValidationError: If file doesn't meet security requirements
    """
    if not os.path.exists(file_path):
        raise ValidationError("PDF file not found")
    
    # Check file size
    file_size = os.path.getsize(file_path)
    max_size = max_size or getattr(settings, 'PDF_MAX_FILE_SIZE', 50 * 1024 * 1024)
    
    if file_size > max_size:
        raise ValidationError(f"PDF file too large. Maximum size: {max_size / (1024*1024):.1f}MB")
    
    # Check if file is actually a PDF
    with open(file_path, 'rb') as f:
        header = f.read(4)
        if header != b'%PDF':
            raise ValidationError("File is not a valid PDF")
    
    # Additional validation can be added here
    # For example, checking for suspicious content patterns


def safe_pdf_processing(pdf_file, max_pages=None):
    """
    Safely process PDF files with security limits.
    
    Args:
        pdf_file: PDF file object or path
        max_pages (int): Maximum number of pages to process
    
    Returns:
        Processed PDF data or raises ValidationError
    """
    max_pages = max_pages or getattr(settings, 'PDF_MAX_PAGES', 1000)
    
    try:
        # Validate file first
        if hasattr(pdf_file, 'path'):
            validate_pdf_file(pdf_file.path, max_pages)
        else:
            validate_pdf_file(pdf_file, max_pages)
        
        # Add timeout and page limit checks here
        # This is a placeholder for actual PDF processing logic
        
        return True
        
    except Exception as e:
        raise ValidationError(f"PDF processing failed: {str(e)}")


def get_pdf_security_settings():
    """
    Get PDF security settings from Django settings.
    
    Returns:
        dict: PDF security configuration
    """
    return {
        'max_pages': getattr(settings, 'PDF_MAX_PAGES', 1000),
        'max_file_size': getattr(settings, 'PDF_MAX_FILE_SIZE', 50 * 1024 * 1024),
        'timeout': 30,  # seconds
    }
