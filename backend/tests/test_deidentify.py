"""Regression tests for de-identification (PRD section 6/7: identifiers must be
removed before any external model call)."""

from app.book_appointment.deidentify import deidentify


def test_empty_text_returns_empty():
    result = deidentify("")
    assert result.text == ""
    assert result.removed == {}


def test_scrubs_name_phone_email():
    result = deidentify(
        "my name is Rahul Sharma, call +91 9876543210 or rahul@mail.com"
    )
    assert "Rahul" not in result.text
    assert "9876543210" not in result.text
    assert "rahul@mail.com" not in result.text
    assert result.removed.get("NAME", 0) >= 1
    assert result.removed.get("PHONE", 0) >= 1
    assert result.removed.get("EMAIL", 0) >= 1


def test_scrubs_titled_name_fully():
    # Regression: "Dr. Anjali Mehta" previously leaked the real name.
    result = deidentify("This is Dr. Anjali Mehta, I have chest pain")
    assert "Anjali" not in result.text
    assert "Mehta" not in result.text
    # Clinical content must survive.
    assert "chest pain" in result.text


def test_preserves_clinical_text_without_pii():
    text = "bad cough and fever for 3 days"
    result = deidentify(text)
    assert result.text == text
    assert result.removed == {}


def test_removed_summary_has_no_raw_values():
    # The summary must be type->count only, never the raw identifier value.
    result = deidentify("contact me at 9876543210")
    assert all(isinstance(v, int) for v in result.removed.values())
