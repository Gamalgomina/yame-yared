"""Erreurs que l'utilisateur peut corriger lui-même."""


class ErreurEtude(ValueError):
    """Erreur expliquée en langage simple à l'utilisateur."""


class BesoinIncomplet(ErreurEtude):
    """Il manque une information que la plateforme ne peut pas deviner."""


class BesoinInfaisable(ErreurEtude):
    """Aucune solution ne répond au besoin avec les hypothèses retenues."""
