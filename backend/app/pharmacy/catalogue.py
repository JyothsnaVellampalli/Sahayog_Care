"""Validate and normalize the supplied catalogue without inferring drug facts."""
import json
import re
from pathlib import Path

SOURCE = Path(__file__).parent / "data" / "medicines.json"
SPECIALTIES = {"cardiology", "orthopedics", "dermatology", "gastroenterology"}


def clean_text(value):
    return " ".join(value.split()) if isinstance(value, str) else value


def load_catalogue(path=SOURCE):
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    medicines, brands = [], []
    medicine_ids, brand_ids = set(), set()
    for source in document["medicines"]:
        row = {key: clean_text(source.get(key)) for key in
               ("id", "generic_name", "specialty", "composition")}
        if not re.fullmatch(r"M\d{3}", row["id"] or "") or row["id"] in medicine_ids:
            raise ValueError("Invalid or duplicate medicine ID")
        if row["specialty"] not in SPECIALTIES or not row["generic_name"] or not row["composition"]:
            raise ValueError(f"Incomplete medicine {row['id']}")
        medicine_ids.add(row["id"])
        row["source_details"] = {k: v for k, v in source.items() if k != "brands"}
        medicines.append(row)
        for source_brand in source["brands"]:
            brand = {key: clean_text(source_brand.get(key)) for key in
                     ("brand_id", "brand", "manufacturer", "variant", "source_status")}
            if (not re.fullmatch(r"BR\d{3}", brand["brand_id"] or "")
                    or brand["brand_id"] in brand_ids):
                raise ValueError("Invalid or duplicate brand ID")
            if not brand["brand"] or not brand["variant"] or brand["source_status"] not in {"web_confirmed", "unverified"}:
                raise ValueError(f"Incomplete brand {brand['brand_id']}")
            brand_ids.add(brand["brand_id"])
            brand["medicine_id"] = row["id"]
            brands.append(brand)
    if not medicines or not brands:
        raise ValueError("Empty pharmacy catalogue")
    return medicines, brands
