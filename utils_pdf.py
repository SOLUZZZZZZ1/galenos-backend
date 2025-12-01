
# utils_pdf.py — Conversión de PDF a imágenes para Galenos.pro (Optimizado)
# Requiere PyMuPDF (fitz)
#
# Objetivo:
# - Convertir PDFs médicos (analíticas, informes, estudios de imagen) en
#   una secuencia de imágenes PNG en base64 listas para Vision.
# - Manejar PDFs grandes de forma eficiente (límite razonable de páginas).

import base64
from typing import List

import fitz  # PyMuPDF


def convert_pdf_to_images(pdf_bytes: bytes, max_pages: int = 20, dpi: int = 200) -> List[str]:
    """Convierte las páginas de un PDF en imágenes PNG codificadas en base64.

    - max_pages: límite de páginas a procesar (para evitar PDFs enormes).
    - dpi: resolución para la rasterización (200–300 suele ser suficiente para analíticas).

    Devuelve:
        List[str]: lista de strings base64 (una por página procesada).
    """
    images_b64: List[str] = []

    if not pdf_bytes:
        return images_b64

    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as e:
        print("[PDF] Error abriendo PDF:", e)
        return images_b64

    try:
        total_pages = doc.page_count
        pages_to_process = min(total_pages, max_pages)

        for i in range(pages_to_process):
            try:
                page = doc.load_page(i)
                pix = page.get_pixmap(dpi=dpi)
                img_bytes = pix.tobytes("png")
                b64 = base64.b64encode(img_bytes).decode("utf-8")
                images_b64.append(b64)
            except Exception as e_page:
                print(f"[PDF] Error procesando página {i}:", e_page)
                continue
    finally:
        doc.close()

    return images_b64
