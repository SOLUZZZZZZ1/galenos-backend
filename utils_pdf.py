# utils_pdf.py — Conversión de PDF a imágenes para GPT-4o Vision
# Necesita pymupdf (fitz)

import fitz  # PyMuPDF
import base64


def convert_pdf_to_images(pdf_bytes: bytes):
    """
    Convierte todas las páginas de un PDF en imágenes PNG en base64.
    Retorna lista de strings base64.
    """
    images_b64 = []

    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")

        for page in doc:
            pix = page.get_pixmap(dpi=200)  # 200 DPI para buena lectura IA
            img_bytes = pix.tobytes("png")
            b64 = base64.b64encode(img_bytes).decode("utf-8")
            images_b64.append(b64)

        doc.close()
        return images_b64

    except Exception as e:
        print("[PDF] Error procesando PDF:", e)
        return []
