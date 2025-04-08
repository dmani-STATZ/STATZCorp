"""
Image processing utilities that lazily import dependencies to prevent import conflicts.
"""
import importlib

# Dictionary to store lazily-loaded modules
_modules = {}

def get_module(name):
    """Lazily import a module only when needed"""
    if name not in _modules:
        _modules[name] = importlib.import_module(name)
    return _modules[name]

# Lazy loading functions for each module
def np():
    """Get numpy module"""
    return get_module('numpy')

def fitz():
    """Get PyMuPDF module"""
    return get_module('fitz')

def PyPDF2():
    """Get PyPDF2 module"""
    return get_module('PyPDF2')

def pytesseract():
    """Get pytesseract module"""
    return get_module('pytesseract')

def pdf2image():
    """Get pdf2image module"""
    return get_module('pdf2image')

def Image():
    """Get PIL.Image module"""
    return get_module('PIL.Image')

def ImageDraw():
    """Get PIL.ImageDraw module"""
    return get_module('PIL.ImageDraw') 