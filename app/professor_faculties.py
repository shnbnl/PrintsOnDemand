"""Department and faculty choices offered at professor registration."""

FACULTIES_BY_DEPARTMENT = {
    "MITL": (
        "Chemical Engineering", "Civil Engineering", "Industrial Engineering", "Architecture",
        "Computer Engineering", "Electronics Engineering", "Mechanical Engineering",
        "Electrical Engineering",
    ),
    "ETYCB": (
        "Hospitality Management", "Business Administration", "Global Management",
        "Business Intelligence and Analytics", "BS Marketing", "Tourism Management",
        "Accountancy", "Accounting Information Systems", "Business Program Chair",
    ),
    "CHS": ("Biology", "Psychology"),
    "CCIS": ("Information Technology", "Computer Science"),
    "CAS": ("Multimedia Arts", "Communication"),
    "CMET": ("Marine Engineering", "Marine Transportation"),
    "SHS": (),
}

DELIVERY_LOCATIONS_BY_DEPARTMENT = {
    "MITL": "Einstein Building 1st Floor",
    "CMET": "Einstein Building 1st Floor",
    "CCIS": "Einstein Building 3rd Floor",
    "CAS": "Einstein Building 4th Floor",
    "ETYCB": "Einstein Building 4th Floor",
    "CHS": "Einstein Building 4th Floor",
    "SHS": "Rizal Building",
}

# Existing accounts and orders can retain the former department-code faculty.
LEGACY_FACULTIES = frozenset((*FACULTIES_BY_DEPARTMENT, "GE", "IECELL"))
ALL_FACULTIES = frozenset(
    faculty for choices in FACULTIES_BY_DEPARTMENT.values() for faculty in choices
) | LEGACY_FACULTIES


def faculty_for_account(department: str | None, selection: str | None) -> str | None:
    """Use the registered faculty, or the department for SHS and older accounts."""
    if selection and selection in FACULTIES_BY_DEPARTMENT.get(department, ()):
        return selection
    if not selection and department in LEGACY_FACULTIES:
        return department
    return None
