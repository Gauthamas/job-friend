import re

MONTH_ABBREVIATIONS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

_ISO = re.compile(r"^\d{4}-\d{2}$")
_SLASH = re.compile(r"^(\d{1,2})/(\d{4})$")
_MONTH_NAME = re.compile(r"^([A-Za-z]+)\.?\s+(\d{4})$")


def normalize_month(value: str) -> str:
    """Normalize a role start/end date to "YYYY-MM". Formats handled:
    "Apr 2022", "04/2022", "2022-04". Anything else (e.g. "Present") is
    returned unchanged rather than raised on, since resumes commonly use
    open-ended end dates that aren't a month at all.
    """
    value = value.strip()

    if _ISO.match(value):
        return value

    m = _SLASH.match(value)
    if m:
        month, year = m.groups()
        return f"{year}-{int(month):02d}"

    m = _MONTH_NAME.match(value)
    if m:
        month_name, year = m.groups()
        month_num = MONTH_ABBREVIATIONS.get(month_name.lower()[:3])
        if month_num:
            return f"{year}-{month_num:02d}"

    return value
