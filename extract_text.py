import re
import PyPDF2

pdf_path = 'test_file.PDF'

patterns = {
    'contract_number': r'[A-Z0-9]{6}-[0-9]{2}-[A-Z0-9]{1}-[0-9]{4}',
    'award_date': r'[0-9]{2}-[A-Z]{3}-[0-9]{4}',
    'buyer': r'[A-Z]{3,4} [A-Z0-9]{3,4}',
    'po_number': r'[A-Z0-9]{3,4}-[0-9]{3,4}',
    'contract_type': r'[A-Z]{3,4} [A-Z0-9]{3,4}',
    'due_date': r'[0-9]{2}-[A-Z]{3}-[0-9]{4}'
}

def search_pattern(text, pattern):
    match = re.search(pattern, text)
    return match.group() if match else 'Not found'

def extract_text_from_pdf(pdf_path):
    try:
        with open(pdf_path, 'rb') as file:
            reader = PyPDF2.PdfReader(file, strict=False)
            return [page.extract_text() for page in reader.pages]
    except Exception as e:
        print(f"Error extracting text from PDF: {e}")
        return []

if __name__ == "__main__":
    extract_text = extract_text_from_pdf(pdf_path)
    results = {key: 'Not found' for key in patterns.keys()}

    text_index = 0
    while text_index < len(extract_text) and 'Not found' in results.values():
        text = extract_text[text_index]
        split_text = re.split("\n", text)
        for line in split_text:
            items = line.split(",")
            for item in items:
                for key, pattern in patterns.items():
                    if results[key] == 'Not found':
                        result = search_pattern(item, pattern)
                        if result != 'Not found':
                            results[key] = result
        text_index += 1

    # Print final results
    for key, value in results.items():
        print(f"{key.replace('_', ' ').title()}: {value}")




# if __name__ == "__main__":
#     extract_text = extract_text_from_pdf(pdf_path)
#     line_number = 1
#     contract_number_pattern = r'[A-Z0-9]{5}-[0-9]{2}-[A-Z0-9]{1}-[0-9]{4}'
#     contract_number = 'Not found'
#     award_date = 'Not found'
#     buyer = 'Not found'
#     po_number = 'Not found'
#     contract_type = 'Not found'
#     due_date = 'Not found'
#     for text in extract_text:
#         split_text = re.split("\n", text.lower())
#         for line in split_text:
#             items = line.split(",")
#             for item in items:
#                 contract_number = contract_number(item)
#                 award_date = award_date(item)
#                 buyer = buyer(item)
#                 po_number = po_number(item)
#                 contract_type = contract_type(item)
#                 due_date = due_date(item)
#                 if contract_number:
#                     print(f"{line_number}: {contract_number}")
#                 if award_date:
#                     print(f"{line_number}: {award_date}")
#                 if buyer:
#                     print(f"{line_number}: {buyer}")
#                 if po_number:
#                     print(f"{line_number}: {po_number}")
#                 if contract_type:
#                     print(f"{line_number}: {contract_type}")
#                 if due_date:
#                     print(f"{line_number}: {due_date}")
#                 line_number += 1




        



