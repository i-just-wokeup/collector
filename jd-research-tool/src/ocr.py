from PIL import Image
import pytesseract
import cv2
from pathlib import Path
import shutil

def preprocess_image(image_path):
    img = cv2.imread(image_path)

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    thresh = cv2.threshold(gray, 150, 225, cv2.THRESH_BINARY)[1]

    img = cv2.resize(thresh,None, fx=2, fy=2)
    
    return img

def _resolve_tesseract_cmd() -> str | None:
    # 1) Try system PATH first.
    path_cmd = shutil.which("tesseract")
    if path_cmd:
        return path_cmd

    # 2) Fallback to common Windows install paths.
    candidate_paths = [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ]
    for candidate in candidate_paths:
        if Path(candidate).exists():
            return candidate

    return None


def extract_text_from_image(image_path: str) -> str:

    image = Image.open(image_path)

    custom_config = r'--oem 3 --psm 6'

    try:
        tesseract_cmd = _resolve_tesseract_cmd()
        if tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = tesseract_cmd

        text = pytesseract.image_to_string(
            image,
            lang="eng+kor",
            config=custom_config
        )
    except pytesseract.TesseractNotFoundError as error:
        print("[ERROR] Tesseract OCR을 찾을 수 없습니다. Tesseract를 설치하고 시스템 PATH에 등록해 주세요.")
        raise RuntimeError("Tesseract OCR is not installed or not in PATH.") from error
    
    return text.strip()
