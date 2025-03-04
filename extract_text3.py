import fitz  # PyMuPDF

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

# Path to the PDF file
pdf_path = 'test_file.PDF'

# Open the PDF document
pdf_document = fitz.open(pdf_path)

# Define the box areas for each field as percentages (left, upper, right, lower)
coordinates = {
    'contract_number': (35 / 612, 67 / 792, 179 / 612, 88 / 792),  #Contract number need to be extracted from the text
    'award_date': (297 / 612, 73 / 792, 379 / 612, 88 / 792),  #Date need to be extracted from the text
    'buyer': (35 / 612, 97 / 792, 212 / 612, 143 / 792),    #Buyer and Address need to be extracted from the text
    'po_number': (382 / 612, 67 / 792, 502 / 612, 88 / 792),
    'contract_type_purchase': (100 / 612, 289 / 792, 114 / 612, 312 / 792),  #Boolean
    'contract_type_delivery': (100 / 612, 272 / 792, 114 / 612, 287 / 792),  #Boolean
    'due_date_days': (382 / 612, 156 / 792, 502 / 612, 167 / 792),  #Days need to be extracted from the text
    'contract_amount': (495 / 612, 527 / 792, 576 / 612, 538 / 792)  #Amount need to be extracted from the text
}

# Initialize results dictionary
results = {key: 'Not found' for key in coordinates.keys()}

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
        ocr_result = extract_text_from_box(first_page, box)
        results[key] = ocr_result
        print(f"Extracted Text for {key.replace('_', ' ').title()}:\n{ocr_result}\n")

# Print final results
for key, value in results.items():
    print(f"{key.replace('_', ' ').title()}: {value}")
