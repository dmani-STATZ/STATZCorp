# Image Processing and Excel Utilities

This package provides lazy-loading approaches for importing libraries that can cause conflicts in production WSGI environments.

## Image Processing Utilities

Provides a lazy-loading approach for image processing libraries, preventing import conflicts especially in production WSGI environments.

### Problem Solved

1. NumPy and other dependencies can cause conflicts when imported multiple times or in specific orders
2. In production WSGI environments, modules might be loaded in different ways than in development
3. The "CPU dispatcher tracer already initialized" error occurs when NumPy's initialization conflicts with itself

### Usage

Instead of importing these libraries directly in your views or other modules:

```python
import numpy as np
import pypdf
import pytesseract
import pdf2image
import fitz  # PyMuPDF
from PIL import Image, ImageDraw
```

Import the lazy-loading functions and call them when needed:

```python
from contracts.utils.image_processing import np, fitz, pypdf, pytesseract, pdf2image, Image, ImageDraw

# Use as functions
numpy_array = np().array([1, 2, 3])
pdf_doc = fitz().open(pdf_path)
pil_image = Image().open("image.jpg")
```

## Excel Utilities

Provides a lazy-loading approach for openpyxl, which also depends on NumPy.

### Usage

Instead of importing openpyxl directly:

```python
from openpyxl import Workbook
from openpyxl.utils import get_column_letter
from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
```

Import the lazy-loading functions and call them when needed:

```python
from contracts.utils.excel_utils import Workbook, get_column_letter, PatternFill, Font, Alignment, Border, Side

# Use as functions that return the actual classes
wb = Workbook()()  # Note the double parentheses
column = get_column_letter()(1)  # Call as function
header_fill = PatternFill()(start_color="4F46E5", end_color="4F46E5", fill_type="solid")
```

## Benefits

1. Prevents initialization conflicts by loading libraries only when needed
2. Avoids the "CPU dispatcher tracer already initialized" error in WSGI environments 
3. Reduces memory usage for requests that don't use these libraries
4. Makes application startup faster and more reliable
5. Centralizes dependency management 