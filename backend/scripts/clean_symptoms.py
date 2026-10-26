"""Clean the Kaggle disease-symptom severity dataset into a canonical seed.

Source: References/Symptom-severity.csv (from the Kaggle
"disease-symptom-description-dataset"). The file has two columns:
`Symptom` (snake_case token) and `weight` (integer 1-7).

This script:
  * de-duplicates symptoms (the raw file repeats `fluid_overload`),
  * drops entries that are not patient-facing symptoms,
  * drops `extra_marital_contacts` (PRD section 14 forbids its use anywhere),
  * assigns a stable ID (S001, S002, ...) in sorted order so IDs do not shift
    between runs,
  * builds a human-readable label for the UI,
  * writes `backend/app/book_appointment/data/symptoms.json`.

Run from the repo root or backend/:
    python backend/scripts/clean_symptoms.py
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

# Resolve paths relative to the repository root regardless of CWD.
BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
SOURCE_CSV = REPO_ROOT / "References" / "Symptom-severity.csv"
OUTPUT_JSON = BACKEND_DIR / "app" / "book_appointment" / "data" / "symptoms.json"

# Entries in the raw CSV that are not patient-selectable symptoms.
# `prognosis` is a dataset artefact (the label column leaked into severity).
# `extra_marital_contacts` is forbidden by PRD section 14.
EXCLUDED_TOKENS = {
    "prognosis",
    "extra_marital_contacts",
}

# A few tokens have awkward spelling in the dataset; map to clean labels.
LABEL_OVERRIDES = {
    "cold_hands_and_feets": "Cold hands and feet",
    "foul_smell_ofurine": "Foul smell of urine",
    "toxic_look_(typhos)": "Toxic look",
    "swelled_lymph_nodes": "Swollen lymph nodes",
    "swollen_extremeties": "Swollen extremities",
    "dischromic_patches": "Discoloured skin patches",
    "spotting_urination": "Spotting during urination",
    "continuous_feel_of_urine": "Continuous urge to urinate",
    "yellow_crust_ooze": "Yellow crust or ooze",
}


def to_label(token: str) -> str:
    """Turn a snake_case symptom token into a readable label."""
    if token in LABEL_OVERRIDES:
        return LABEL_OVERRIDES[token]
    words = token.replace("_", " ").strip()
    return words[:1].upper() + words[1:]


def load_rows(path: Path) -> dict[str, int]:
    """Read the CSV into a {token: weight} dict, keeping the max weight on dupes."""
    if not path.exists():
        raise FileNotFoundError(
            f"Expected the severity dataset at {path}. "
            "Add References/Symptom-severity.csv before running."
        )

    weights: dict[str, int] = {}
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            token = (row.get("Symptom") or "").strip().lower()
            raw_weight = (row.get("weight") or "").strip()
            if not token or not raw_weight:
                continue
            try:
                weight = int(raw_weight)
            except ValueError:
                continue
            # Duplicate tokens (e.g. fluid_overload) keep the higher weight.
            weights[token] = max(weights.get(token, 0), weight)
    return weights


def build_symptoms(weights: dict[str, int]) -> list[dict]:
    """Produce the canonical, ID-stamped symptom list."""
    tokens = sorted(t for t in weights if t not in EXCLUDED_TOKENS)
    symptoms = []
    for index, token in enumerate(tokens, start=1):
        symptoms.append(
            {
                "id": f"S{index:03d}",
                "code": token,
                "label": to_label(token),
                "weight": weights[token],
            }
        )
    return symptoms


def main() -> None:
    weights = load_rows(SOURCE_CSV)
    symptoms = build_symptoms(weights)

    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "source": "Kaggle disease-symptom-description-dataset (Symptom-severity.csv)",
        "weight_scale": "1 (mild) to 7 (severe)",
        "excluded": sorted(EXCLUDED_TOKENS),
        "count": len(symptoms),
        "symptoms": symptoms,
    }
    OUTPUT_JSON.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(symptoms)} symptoms to {OUTPUT_JSON}")


if __name__ == "__main__":
    main()
