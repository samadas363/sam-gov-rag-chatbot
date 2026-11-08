"""Target NAICS + PSC codes and lookup helpers."""

TARGET_NAICS = ["541370", "541511", "518210", "541620"]
TARGET_PSC = ["R425", "R429", "B510", "T002"]

NAICS_TITLES = {
    "541370": "Surveying and Mapping (except Geophysical) Services",
    "541511": "Custom Computer Programming Services",
    "518210": "Data Processing, Hosting, and Related Services",
    "541620": "Environmental Consulting Services",
}

PSC_TITLES = {
    "R425": "Engineering / Technical Support",
    "R429": "Disaster Planning Support",
    "B510": "Environmental Studies & Analysis",
    "T002": "Cartography",
}


def label(code: str) -> str:
    code = (code or "").strip()
    return f"{code} - {NAICS_TITLES[code]}" if code in NAICS_TITLES else (code or "N/A")


def psc_label(code: str) -> str:
    code = (code or "").strip()
    return f"{code} - {PSC_TITLES[code]}" if code in PSC_TITLES else (code or "N/A")
