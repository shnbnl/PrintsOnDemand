"""Department and faculty choices offered at professor registration."""

FACULTIES_BY_DEPARTMENT = {
    "MITL": (
        "Chemical Engineering", "Industrial Engineering", "Architecture",
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
    "GE": (),
    "SHS": (),
}

# Existing accounts and orders can retain the former department-code faculty.
LEGACY_FACULTIES = frozenset((*FACULTIES_BY_DEPARTMENT, "IECELL"))
ALL_FACULTIES = frozenset(
    faculty for choices in FACULTIES_BY_DEPARTMENT.values() for faculty in choices
) | LEGACY_FACULTIES


def faculty_for_account(department: str | None, selection: str | None) -> str | None:
    """Use the registered faculty, or the department for GE/SHS and older accounts."""
    if selection and selection in FACULTIES_BY_DEPARTMENT.get(department, ()):
        return selection
    if not selection and department in LEGACY_FACULTIES:
        return department
    return None
