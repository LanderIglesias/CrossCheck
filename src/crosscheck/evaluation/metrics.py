"""Métricas de la evaluación de la Fase 10.

Con muestras pequeñas (decenas de casos) el intervalo normal engaña: se sale
de [0, 1] y da anchura cero con 0 o n aciertos. Wilson no tiene ese problema,
así que es el que acompaña a cada ratio.
"""

from __future__ import annotations

import math


def wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Intervalo de Wilson para una proporción; (0.0, 0.0) si no hay muestras."""
    if n == 0:
        return (0.0, 0.0)
    p = successes / n
    denom = 1 + z**2 / n
    centre = (p + z**2 / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / denom
    return (centre - half, centre + half)


def precision_recall(pairs: list[tuple[str, str]], positive: str = "discrepant") -> dict:
    """Precisión y recall de la clase `positive` sobre pares (predicted, gold).

    Un ratio sin denominador es None, no 0: "no medible" no es "falla todo".
    """
    tp = sum(1 for p, g in pairs if p == positive and g == positive)
    fp = sum(1 for p, g in pairs if p == positive and g != positive)
    fn = sum(1 for p, g in pairs if p != positive and g == positive)
    tn = len(pairs) - tp - fp - fn
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": tp / (tp + fp) if tp + fp else None,
        "recall": tp / (tp + fn) if tp + fn else None,
        "precision_ci": wilson_interval(tp, tp + fp),
        "recall_ci": wilson_interval(tp, tp + fn),
        "n": len(pairs),
    }
