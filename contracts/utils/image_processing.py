"""
Image processing utilities that properly manage numpy imports.
"""
import numpy as np  # Import numpy first to avoid conflicts
import fitz  # PyMuPDF
import PyPDF2
import pytesseract
import pdf2image
from PIL import Image, ImageDraw

# Re-export the modules to maintain the same interface
__all__ = ['np', 'fitz', 'PyPDF2', 'pytesseract', 'pdf2image', 'Image', 'ImageDraw'] 