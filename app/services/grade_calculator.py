"""Yiriba SaaS — Shared grade calculation functions.

Single source of truth for:
- Overall average calculation
- Discipline integration (conduct score or general_average deduction)
- Mention determination

Used by both bulletin_service.py and pdf_service.py to avoid duplication.
"""


def calculate_overall_average(subject_averages: list[dict]) -> float | None:
    """Calculate weighted average from subject data.

    Each dict in subject_averages must have:
    - "average": float | None (subject average out of 20)
    - "coefficient": int (subject coefficient)

    Returns the weighted average rounded to 2 decimal places,
    or None if no subject has any grade (incomplete bulletin).
    """
    total_pts = 0.0
    total_cfs = 0
    for s in subject_averages:
        avg = s.get("average")
        coeff = s.get("coefficient", 1)
        if avg is not None:
            total_pts += avg * coeff
            total_cfs += coeff
    if total_cfs == 0:
        return None  # aucune note saisie → pas de moyenne calculable
    return round(total_pts / total_cfs, 2)


def calculate_conduct_score(total_deductions: float) -> float:
    """Calculate conduct score: 20 - total deductions, floor at 0.

    This is the score displayed separately on the bulletin
    in 'conduct' mode.
    """
    return max(0.0, round(20.0 - total_deductions, 1))


def apply_discipline(
    overall_average: float,
    discipline_mode: str,
    total_deductions: float,
) -> dict:
    """Apply discipline according to the school's mode.

    Args:
        overall_average: Raw academic average (before discipline)
        discipline_mode: "conduct" or "general_average"
        total_deductions: Sum of active disciplinary record points

    Returns:
        {
            "display_average": float,   # Average to show on bulletin
            "raw_average": float,       # Academic average before discipline
            "discipline_deduction": float,  # Points deducted (0 if conduct mode)
            "discipline_line": str | None,  # Text for bulletin footer (None in conduct mode)
            "conduct_score": float | None,  # Conduct score (None in general_average mode)
        }
    """
    if discipline_mode == "general_average" and total_deductions > 0:
        display_avg = max(0.0, round(overall_average - total_deductions, 2))
        return {
            "display_average": display_avg,
            "raw_average": overall_average,
            "discipline_deduction": total_deductions,
            "discipline_line": (
                f"Moyenne académique: {overall_average:.2f} "
                f"dont -{total_deductions:.2f} pts de discipline"
            ),
            "conduct_score": None,
        }
    else:
        # conduct mode: discipline shown separately, average unchanged
        conduct = calculate_conduct_score(total_deductions)
        return {
            "display_average": overall_average,
            "raw_average": overall_average,
            "discipline_deduction": 0.0,
            "discipline_line": None,
            "conduct_score": conduct,
        }


def get_mention(average: float) -> str:
    """Get mention based on configurable thresholds (default)."""
    if average >= 16:
        return "Félicitations"
    elif average >= 14:
        return "Encouragements"
    elif average >= 12:
        return "Tableau d'honneur"
    elif average >= 10:
        return "Passable"
    else:
        return "Avertissement"


def get_mention_color(mention: str) -> str:
    """Return CSS color for a mention."""
    colors = {
        "Félicitations": "#1b5e20",
        "Encouragements": "#2e7d32",
        "Tableau d'honneur": "#0E5C3F",
        "Passable": "#f57f17",
        "Avertissement": "#c62828",
    }
    return colors.get(mention, "#333")


def get_mention_bg(mention: str) -> str:
    """Return CSS background for a mention."""
    colors = {
        "Félicitations": "#e8f5e9",
        "Encouragements": "#e8f5e9",
        "Tableau d'honneur": "#f0f8f0",
        "Passable": "#fff8e1",
        "Avertissement": "#fce4ec",
    }
    return colors.get(mention, "#f5f5f5")


def conduct_appreciation(score: float) -> str:
    """Appreciation text for conduct score."""
    if score >= 18:
        return "Excellent"
    elif score >= 15:
        return "Très bien"
    elif score >= 12:
        return "Bien"
    elif score >= 9:
        return "Passable"
    else:
        return "À améliorer"
