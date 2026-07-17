from pypdf import PdfReader

reader = PdfReader("data/uber_10k.pdf")
print(f"Total pages: {len(reader.pages)}")

# נחלץ טקסט מכמה עמודים ונחפש עמוד עם טבלה פיננסית.
# בדוחות 10-K, הדוחות הכספיים הם בדרך כלל באמצע-סוף. ננסה טווח.
for page_num in range(60, 75):
    text = reader.pages[page_num].extract_text()
    # נדפיס רק עמודים שנראים כמו טבלה פיננסית (מכילים $ ומספרים רבים)
    if text.count("$") > 5:
        print(f"\n{'='*70}")
        print(f"PAGE {page_num}  (looks like a financial table)")
        print(f"{'='*70}")
        print(text[:1200])
        break