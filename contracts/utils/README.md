# Image Processing Utilities

This module provides a lazy-loading approach for importing image processing libraries, preventing import conflicts especially in production WSGI environments.

## Problem Solved

1. NumPy and other dependencies can cause conflicts when imported multiple times or in specific orders
2. In production WSGI environments, modules might be loaded in different ways than in development
3. The "CPU dispatcher tracer already initialized" error occurs when NumPy's initialization conflicts with itself

## Usage

Instead of importing these libraries directly in your views or other modules:

```python
import numpy as np
import PyPDF2
import pytesseract
import pdf2image
import fitz  # PyMuPDF
from PIL import Image, ImageDraw
```

Import the lazy-loading functions and call them when needed:

```python
from contracts.utils.image_processing import np, fitz, PyPDF2, pytesseract, pdf2image, Image, ImageDraw

# Use as functions
numpy_array = np().array([1, 2, 3])
pdf_doc = fitz().open(pdf_path)
pil_image = Image().open("image.jpg")
```

## Benefits

1. Prevents initialization conflicts by loading libraries only when needed
2. Avoids the "CPU dispatcher tracer already initialized" error in WSGI environments 
3. Reduces memory usage for requests that don't use these libraries
4. Makes application startup faster and more reliable
5. Centralizes dependency management 