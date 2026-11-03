"""PDF text-extraction tests; pypdf is mocked so no real file is needed."""
from types import SimpleNamespace

from app.search import reports_text


def test_non_pdf_mime_returns_none_without_attempting_extraction():
    assert reports_text.extract_text(b"anything", "image/png") is None
    assert reports_text.extract_text(b"anything", "image/jpeg") is None


def test_pdf_with_text_layer_is_extracted(monkeypatch):
    class FakeReader:
        def __init__(self, _buf):
            self.pages = [SimpleNamespace(extract_text=lambda: "Hemoglobin 13.5 g/dL"),
                          SimpleNamespace(extract_text=lambda: "Normal range 12-16")]
    monkeypatch.setattr("pypdf.PdfReader", FakeReader)
    text = reports_text.extract_text(b"%PDF-fake", "application/pdf")
    assert text == "Hemoglobin 13.5 g/dL\nNormal range 12-16"


def test_scanned_pdf_with_no_text_layer_returns_none(monkeypatch):
    class FakeReader:
        def __init__(self, _buf):
            self.pages = [SimpleNamespace(extract_text=lambda: "")]
    monkeypatch.setattr("pypdf.PdfReader", FakeReader)
    assert reports_text.extract_text(b"%PDF-fake", "application/pdf") is None


def test_corrupt_pdf_is_logged_and_returns_none(monkeypatch):
    def broken(_buf):
        raise ValueError("not a PDF")
    monkeypatch.setattr("pypdf.PdfReader", broken)
    assert reports_text.extract_text(b"garbage", "application/pdf") is None
