# Image Processing Utilities

This module provides a centralized place for importing image processing libraries that depend on NumPy to avoid conflicts.

## Problem Solved

Multiple imports of NumPy (sometimes direct, sometimes through different packages) can cause conflicts, especially when deploying the application.

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

Import them from this utility module:

```python
from contracts.utils.image_processing import np, fitz, PyPDF2, pytesseract, pdf2image, Image, ImageDraw
```

## Benefits

1. Ensures NumPy is imported before other packages that might depend on it
2. Centralizes version management
3. Avoids import conflicts
4. Makes it easier to update or modify image processing dependencies across the app 