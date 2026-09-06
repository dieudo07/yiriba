"""Yiriba SaaS — Student and Parent enums."""

import enum


class StudentStatus(str, enum.Enum):
    """Statut d'un élève — remplace l'ancien is_active: bool."""
    ACTIVE = "active"              # Inscrit et fréquente l'école
    INACTIVE = "inactive"          # Désinscrit temporairement (maladie, etc.)
    GRADUATED = "graduated"        # Diplômé (a terminé le cycle)
    TRANSFERRED = "transferred"    # Transféré vers une autre école
    WITHDRAWN = "withdrawn"        # Retiré définitivement


class ParentRole(str, enum.Enum):
    """Rôle du parent/tuteur par rapport à l'élève."""
    FATHER = "father"      # Père
    MOTHER = "mother"      # Mère
    GUARDIAN = "guardian"   # Tuteur légal
    OTHER = "other"        # Autre (frère aîné, oncle, etc.)
