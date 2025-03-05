import fitz  # PyMuPDF


# Path to the PDF file
pdf_path = 'test_file.PDF'



# Define the box areas for each field as percentages (left, upper, right, lower)
Width = 1224
Height = 1584

coordinates = {
    'contract_number': (73 / Width, 141 / Height, 359 / Width, 174 / Height),
    'award_date': (592 / Width, 157 / Height, 760 / Width, 174 / Height),
    'buyer': (73 / Width, 201 / Height, 428 / Width, 283 / Height),
    'po_number': (787 / Width, 141 / Height, 1002 / Width, 174 / Height),
    'contract_type_purchase': (201 / Width, 576 / Height, 228 / Width, 621 / Height),
    'contract_type_delivery': (201 / Width, 541 / Height, 228 / Width, 571 / Height),
    'due_date_days': (787 / Width, 315 / Height, 1002 / Width, 334 / Height),
    'contract_amount': (1002 / Width, 1054 / Height, 1150 / Width, 1075 / Height)
}

# Initialize results dictionary
results = {key: 'Not found' for key in coordinates.keys()}

# Convert coordinates to percentages of the height and width of the page
def convert_coordinates_to_percentages(coordinates, width, height):
    percentages = {}
    for key, (left, upper, right, lower) in coordinates.items():
        percentages[key] = (
            left / width,
            upper / height,
            right / width,
            lower / height
        )
    return percentages

# Extract text from a specific box area of the PDF page
def extract_text_from_box(page, box):
    text = page.get_textbox(box)
    return text.strip()

# Open the PDF document
pdf_document = fitz.open(pdf_path)

# Extract text from the specific box areas of the first page using percentages
if pdf_document.page_count > 0:
    first_page = pdf_document.load_page(0)
    width, height = first_page.rect.width, first_page.rect.height
    
    # Convert percentages back to coordinates based on the page size
    new_coordinates = {key: (
        left_pct * width,
        upper_pct * height,
        right_pct * width,
        lower_pct * height
    ) for key, (left_pct, upper_pct, right_pct, lower_pct) in coordinates.items()}


    for key, box in new_coordinates.items():
        # Extract text from the current box
        ocr_result = extract_text_from_box(first_page, box)
        results[key] = ocr_result


# Print final results
for key, value in results.items():
    print(f"{key.replace('_', ' ').title()}: {value}")
