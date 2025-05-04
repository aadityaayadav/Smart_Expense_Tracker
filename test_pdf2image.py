from pdf2image import convert_from_path
images = convert_from_path(r"C:\Users\anuj2\OneDrive\Documents\SmartExpenseTracker\PhonePe_Statement_Mar2025_Apr2025_removed.pdf", poppler_path=r"C:\Users\anuj2\Downloads\Release-24.08.0-0\poppler-24.08.0\Library\bin")
print(f"Converted {len(images)} pages")