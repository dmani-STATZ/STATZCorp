import fitz  # PyMuPDF
from PIL import Image
import io

# Convert PDF to images
def pdf_to_images(pdf_path):
    pdf_document = fitz.open(pdf_path)
    images = []
    for page_num in range(len(pdf_document)):
        page = pdf_document.load_page(page_num)
        pix = page.get_pixmap()
        img = Image.open(io.BytesIO(pix.tobytes()))
        images.append(img)
    return images

# Path to the PDF file
pdf_path = 'test_file.PDF'

# Convert PDF to images
images = pdf_to_images(pdf_path)

# Save the first page image to a file for measurement
if images:
    first_page_image = images[0]
    first_page_image.save("first_page_image.png")
    print("The first page of the PDF has been saved as 'first_page_image.png'.")
else:
    print("No images found in the PDF.")