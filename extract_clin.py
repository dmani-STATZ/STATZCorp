import fitz  # PyMuPDF
import re

# Path to the PDF file
pdf_path = 'test_file.PDF'

# Open the PDF document
pdf_document = fitz.open(pdf_path)

# Initialize an empty string to store the text
pdf_text = ""

# Iterate through each page in the PDF
for page_num in range(pdf_document.page_count):
    # Load the page
    page = pdf_document.load_page(page_num)
    # Extract text from the page
    pdf_text += page.get_text()

# Define patterns to extract data
patterns = {
    'nsn_code': r'SUPPLIES/SERVICES:\s*([A-Z0-9\-]+)',
    'item_description': r'ITEM DESCRIPTION:\s*\n\s*\n([^\n]+)',
    'inspection_point': r'INSPECTION POINT:\s*(ORIGIN|DESTINATION)',
    'clin_line': r'(\d{4})\s+([A-Z0-9\-]+)\s+(\d+\.?\d*)\s+(\w+)\s+\$\s*(\d+\.?\d*)\s+\$\s*(\d+\.?\d*)\s+([^\n]+)',
    'fob': r'FOB:\s*(ORIGIN|DESTINATION)',
    'delivery_date': r'DELIVERY DATE:\s*(\d{4}\s*[A-Z]{3}\s*\d{2})'
}
# Define the header pattern to locate the CLIN data section
header_pattern = re.compile(r'ITEM NO\.\s+SUPPLIES/SERVICES\s+QUANTITY\s+UNIT\s+UNIT PRICE\s+AMOUNT')


# Extract data using regex patterns
extracted_data = {}
for key, pattern in patterns.items():
    match = re.search(pattern, pdf_text)
    if match:
        extracted_data[key] = match.group(1)
    else:
        extracted_data[key] = 'Not found'

# Print extracted data
for key, value in extracted_data.items():
    print(f"{key.replace('_', ' ').title()}: {value}")

# Function to extract and store CLIN data
def extract_clin_data(text, clin_pattern, inspection_point_pattern, fob_pattern, delivery_date_pattern):
    clin_data = []
    
    # Extract CLIN data
    for match in clin_pattern.finditer(text):
        clin_number, nsn, order_qty, unit, unit_price, po_amount, description = match.groups()
        
        # Extract inspection point, FOB, and delivery date
        inspection_point_match = inspection_point_pattern.search(text)
        fob_match = fob_pattern.search(text)
        delivery_date_match = delivery_date_pattern.search(text)
        
        inspection_point = inspection_point_match.group(1) if inspection_point_match else None
        fob = fob_match.group(1) if fob_match else None
        delivery_date = delivery_date_match.group(1) if delivery_date_match else None
        
        clin_data.append({
            "clin_number": clin_number,
            "nsn": nsn,
            "order_qty": order_qty,
            "unit": unit,
            "unit_price": unit_price,
            "po_amount": po_amount,
            "description": description,
            "inspection_point": inspection_point,
            "fob": fob,
            "delivery_date": delivery_date
        })
    
    return clin_data

# Define the header pattern to locate the CLIN data section
header_pattern = re.compile(r'ITEM NO\.\s+SUPPLIES/SERVICES\s+QUANTITY\s+UNIT\s+UNIT PRICE\s+AMOUNT')

# Find the header line
header_match = header_pattern.search(pdf_text)

if header_match:
    # Extract the text starting from the header line
    start_index = header_match.end()
    clin_text = pdf_text[start_index:]

    # Extract CLIN data from the PDF text
    clin_data = extract_clin_data(clin_text, re.compile(r'(\d{4})\s+([A-Z0-9\-]+)\s+(\d+\.?\d*)\s+(\w+)\s+\$\s*(\d+\.?\d*)\s+\$\s*(\d+\.?\d*)\s+([^\n]+)'), re.compile(patterns['inspection_point']), re.compile(patterns['fob']), re.compile(patterns['delivery_date']))

    # Print the extracted CLIN data
    for clin in clin_data:
        print(clin)
else:
    print("Header not found. Unable to extract CLIN data.")