"""
Excel utilities that lazily import openpyxl to prevent NumPy conflicts in production.
"""
import importlib

# Dictionary to store lazily-loaded modules
_modules = {}

def get_module(name):
    """Lazily import a module only when needed"""
    if name not in _modules:
        _modules[name] = importlib.import_module(name)
    return _modules[name]

def Workbook():
    """Get openpyxl Workbook class"""
    return get_module('openpyxl').Workbook

def load_workbook():
    """Get openpyxl load_workbook function"""
    return get_module('openpyxl').load_workbook

def get_column_letter():
    """Get column_letter function from openpyxl.utils"""
    return get_module('openpyxl.utils').get_column_letter

def styles():
    """Get all styles from openpyxl"""
    return get_module('openpyxl.styles')

# Individual style classes
def PatternFill():
    """Get PatternFill class from openpyxl.styles"""
    return get_module('openpyxl.styles').PatternFill

def Font():
    """Get Font class from openpyxl.styles"""
    return get_module('openpyxl.styles').Font

def Alignment():
    """Get Alignment class from openpyxl.styles"""
    return get_module('openpyxl.styles').Alignment

def Border():
    """Get Border class from openpyxl.styles"""
    return get_module('openpyxl.styles').Border

def Side():
    """Get Side class from openpyxl.styles"""
    return get_module('openpyxl.styles').Side 