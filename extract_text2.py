import fitz  # PyMuPDF
import pytesseract
from PIL import Image, ImageEnhance, ImageFilter
import io

# Specify the path to the Tesseract executable
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

# Convert PDF to images with higher resolution
def pdf_to_images(pdf_path, zoom_x=2.0, zoom_y=2.0):
    pdf_document = fitz.open(pdf_path)
    images = []
    for page_num in range(len(pdf_document)):
        page = pdf_document.load_page(page_num)
        mat = fitz.Matrix(zoom_x, zoom_y)  # Set the zoom factor for higher resolution
        pix = page.get_pixmap(matrix=mat)
        img = Image.open(io.BytesIO(pix.tobytes()))
        images.append(img)
    return images

# Convert coordinates to percentages of the height and width of the image
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

# Perform OCR on a specific box area of the image with preprocessing
def ocr_on_box_area(image, box):
    cropped_img = image.crop(box)
    cropped_img = cropped_img.convert('L')  # Convert to grayscale
    cropped_img = cropped_img.filter(ImageFilter.MedianFilter())  # Remove noise
    enhancer = ImageEnhance.Contrast(cropped_img)
    cropped_img = enhancer.enhance(2)  # Increase contrast
    cropped_img.show()  # Show the cropped image for verification
    text = pytesseract.image_to_string(cropped_img)
    return text


# Path to the PDF file
pdf_path = 'test_file.PDF'

# Convert PDF to images
images = pdf_to_images(pdf_path)

# Define the box areas for each field (left, upper, right, lower)
coordinates = {
    'contract_number': (35 / 612, 60 / 792, 179 / 612, 88 / 792),
    'award_date': (297 / 612, 60 / 792, 379 / 612, 88 / 792),
    'buyer': (35 / 612, 90 / 792, 212 / 612, 143 / 792),
    'po_number': (382 / 612, 60 / 792, 502 / 612, 88 / 792),
    'contract_type': (64 / 612, 270 / 792, 114 / 612, 312 / 792),
    'due_date': (382 / 612, 145 / 792, 502 / 612, 167 / 792)
}

# Initialize results dictionary
results = {key: 'Not found' for key in coordinates.keys()}

# Perform OCR on the specific box areas of the first page using percentages
if images:
    first_page_image = images[0]
    width, height = first_page_image.size
    
    # Convert percentages back to coordinates based on the image size
    new_coordinates = {key: (
        int(left_pct * width),
        int(upper_pct * height),
        int(right_pct * width),
        int(lower_pct * height)
    ) for key, (left_pct, upper_pct, right_pct, lower_pct) in coordinates.items()}
    
    for key, box in new_coordinates.items():
        ocr_result = ocr_on_box_area(first_page_image, box)
        results[key] = ocr_result.strip()
        print(f"OCR Result for {key.replace('_', ' ').title()}:\n{ocr_result}\n")

# Print final results
for key, value in results.items():
    print(f"{key.replace('_', ' ').title()}: {value}")