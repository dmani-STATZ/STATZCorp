from django.shortcuts import render, redirect
from django.contrib import messages
from django.http import JsonResponse
import tempfile
import os
import re
import io
import logging
import fitz  # PyMuPDF
from PIL import Image
import pdf2image
import pytesseract
from pdfminer.high_level import extract_text

from STATZWeb.decorators import conditional_login_required
from ..models import Contract, Supplier, Clin
from ..forms import ContractForm


@conditional_login_required
def extract_dd1155_data(request):
    if request.method == 'POST' and request.FILES.get('pdf_file'):
        pdf_file = request.FILES['pdf_file']
        
        # Create a temporary file to store the uploaded PDF
        with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as temp_file:
            for chunk in pdf_file.chunks():
                temp_file.write(chunk)
            temp_file_path = temp_file.name
        
        try:
            # Extract text from the PDF
            extraction_results = extract_text_from_pdf(temp_file_path)
            
            # Parse the extracted text to get contract data
            contract_data = parse_dd1155_text(extraction_results)
            
            # Clean up the temporary file
            os.unlink(temp_file_path)
            
            if contract_data:
                # Return the extracted data as JSON
                return JsonResponse({
                    'success': True,
                    'data': contract_data
                })
            else:
                return JsonResponse({
                    'success': False,
                    'error': 'Could not extract data from the PDF. Please check the file format.'
                })
        
        except Exception as e:
            # Log the error
            logging.error(f"Error extracting data from PDF: {str(e)}")
            
            # Clean up the temporary file
            if os.path.exists(temp_file_path):
                os.unlink(temp_file_path)
            
            return JsonResponse({
                'success': False,
                'error': f"Error processing PDF: {str(e)}"
            })
    
    return render(request, 'contracts/dd1155_test.html')


def extract_text_from_pdf(pdf_path):
    """
    Extract text from a PDF file using multiple methods for better accuracy.
    """
    results = {
        'pdfminer_text': '',
        'pymupdf_text': '',
        'ocr_text': ''
    }
    
    # Method 1: Use pdfminer to extract text
    try:
        results['pdfminer_text'] = extract_text(pdf_path)
    except Exception as e:
        logging.error(f"pdfminer extraction error: {str(e)}")
    
    # Method 2: Use PyMuPDF (fitz) to extract text
    try:
        doc = fitz.open(pdf_path)
        pymupdf_text = ""
        for page in doc:
            pymupdf_text += page.get_text()
        results['pymupdf_text'] = pymupdf_text
        doc.close()
    except Exception as e:
        logging.error(f"PyMuPDF extraction error: {str(e)}")
    
    # Method 3: Use OCR if the text extraction methods don't yield good results
    if not results['pdfminer_text'] and not results['pymupdf_text']:
        try:
            # Convert PDF to images
            images = pdf2image.convert_from_path(pdf_path)
            ocr_text = ""
            
            for img in images:
                # Use pytesseract to extract text from the image
                ocr_text += pytesseract.image_to_string(img)
            
            results['ocr_text'] = ocr_text
        except Exception as e:
            logging.error(f"OCR extraction error: {str(e)}")
    
    return results


def parse_dd1155_text(extraction_results):
    """
    Parse the extracted text to identify contract information.
    """
    # Combine all extraction results, prioritizing methods that yielded results
    text = ""
    if extraction_results['pdfminer_text']:
        text = extraction_results['pdfminer_text']
    elif extraction_results['pymupdf_text']:
        text = extraction_results['pymupdf_text']
    elif extraction_results['ocr_text']:
        text = extraction_results['ocr_text']
    
    if not text:
        return None
    
    # Parse the full text to extract all relevant fields
    return parse_full_text(text)


def parse_full_text(text):
    """
    Parse the full text to extract all relevant fields from a DD1155 form.
    """
    # Initialize the contract data dictionary
    contract_data = {
        'contract_num': '',
        'title': '',
        'supplier': {
            'name': '',
            'address': '',
            'cage_code': ''
        },
        'clins': []
    }
    
    # Extract contract number (look for patterns like "CONTRACT NO." or "ORDER NO.")
    contract_num_patterns = [
        r'CONTRACT\s+NO\.\s*([\w\-\/]+)',
        r'ORDER\s+NO\.\s*([\w\-\/]+)',
        r'PURCHASE\s+ORDER\s+NUMBER\s*([\w\-\/]+)'
    ]
    
    for pattern in contract_num_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            contract_data['contract_num'] = match.group(1).strip()
            break
    
    # Extract supplier information
    # Look for sections labeled "CONTRACTOR" or "SUPPLIER"
    supplier_section_patterns = [
        r'CONTRACTOR\s*[:\n](.*?)(?:SHIP\s+TO|DESTINATION|ITEM\s+NO)',
        r'SUPPLIER\s*[:\n](.*?)(?:SHIP\s+TO|DESTINATION|ITEM\s+NO)'
    ]
    
    for pattern in supplier_section_patterns:
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if match:
            supplier_text = match.group(1).strip()
            
            # Extract supplier name (usually the first line)
            supplier_lines = supplier_text.split('\n')
            if supplier_lines:
                contract_data['supplier']['name'] = supplier_lines[0].strip()
                
                # Extract address (remaining lines)
                if len(supplier_lines) > 1:
                    contract_data['supplier']['address'] = '\n'.join(supplier_lines[1:]).strip()
            
            break
    
    # Extract CAGE code
    cage_code_pattern = r'CAGE\s+CODE\s*[:\n]\s*([\w\d]+)'
    match = re.search(cage_code_pattern, text, re.IGNORECASE)
    if match:
        contract_data['supplier']['cage_code'] = match.group(1).strip()
    
    # Extract CLINs (items)
    # Look for sections with item numbers, descriptions, quantities, and prices
    clin_patterns = [
        r'ITEM\s+NO\.\s*(\d+)\s*SUPPLIES.*?QUANTITY\s*(\d+).*?UNIT\s+PRICE\s*\$?\s*([\d,\.]+)',
        r'ITEM\s+(\d+).*?DESCRIPTION.*?QTY\s*(\d+).*?UNIT\s+PRICE\s*\$?\s*([\d,\.]+)'
    ]
    
    for pattern in clin_patterns:
        matches = re.finditer(pattern, text, re.IGNORECASE | re.DOTALL)
        for match in matches:
            clin_num = match.group(1).strip()
            quantity = match.group(2).strip()
            unit_price = match.group(3).strip().replace(',', '')
            
            # Extract description (this is more challenging and may require additional context)
            description_pattern = rf'ITEM\s+NO\.\s*{clin_num}.*?SUPPLIES.*?DESCRIPTION\s*(.*?)(?:QUANTITY|QTY)'
            desc_match = re.search(description_pattern, text, re.IGNORECASE | re.DOTALL)
            description = desc_match.group(1).strip() if desc_match else ''
            
            # Add the CLIN to the contract data
            contract_data['clins'].append({
                'clin_num': clin_num,
                'description': description,
                'quantity': quantity,
                'unit_price': unit_price
            })
    
    # If no CLINs were found using the patterns, try a more general approach
    if not contract_data['clins']:
        # Look for sections that might contain item information
        item_sections = re.findall(r'ITEM\s+(\d+).*?(?=ITEM\s+\d+|$)', text, re.IGNORECASE | re.DOTALL)
        
        for i, section in enumerate(item_sections):
            # Extract basic information
            clin_num = str(i + 1)
            
            # Try to find quantity
            qty_match = re.search(r'QTY.*?(\d+)', section, re.IGNORECASE)
            quantity = qty_match.group(1) if qty_match else '1'
            
            # Try to find price
            price_match = re.search(r'\$\s*([\d,\.]+)', section)
            unit_price = price_match.group(1).replace(',', '') if price_match else '0.00'
            
            # Use the section as the description
            description = section.strip()
            
            # Add the CLIN to the contract data
            contract_data['clins'].append({
                'clin_num': clin_num,
                'description': description,
                'quantity': quantity,
                'unit_price': unit_price
            })
    
    # Extract title/description from the document
    title_patterns = [
        r'DESCRIPTION\s*[:\n](.*?)(?:CONTRACTOR|SUPPLIER|SHIP\s+TO)',
        r'TITLE\s*[:\n](.*?)(?:CONTRACTOR|SUPPLIER|SHIP\s+TO)'
    ]
    
    for pattern in title_patterns:
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if match:
            contract_data['title'] = match.group(1).strip()
            break
    
    # If no title was found, use a default
    if not contract_data['title'] and contract_data['contract_num']:
        contract_data['title'] = f"Contract {contract_data['contract_num']}"
    
    return contract_data 