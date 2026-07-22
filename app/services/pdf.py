from io import BytesIO

from app.core.errors import BadRequestError
from app.schemas.contracts import ExtractedPage


class PDFTextExtractor:
    def extract_pages(self, content: bytes) -> list[ExtractedPage]:
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise RuntimeError("pypdf is required for PDF ingestion") from exc

        try:
            reader = PdfReader(BytesIO(content))
        except Exception as exc:
            raise BadRequestError("Unable to read the uploaded PDF.") from exc

        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception as exc:
                raise BadRequestError(
                    "Encrypted PDFs are not supported unless they have no password."
                ) from exc

        pages: list[ExtractedPage] = []
        for index, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            pages.append(ExtractedPage(page_number=index, text=text))

        if not any(page.text.strip() for page in pages):
            raise BadRequestError("No extractable text was found in the PDF.")

        return pages
