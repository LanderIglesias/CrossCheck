"""Tope de gasto de API para la evaluación de la Fase 10.

El guardia para ANTES de pasarse: comprueba que el gasto más la llamada más
cara observada cabe en el tope, en lugar de contar después de gastar.

ponytail: los reintentos internos del SDK de anthropic (2 por defecto) no se
ven desde aquí; solo se factura la respuesta final, que es la que trae
`usage`. Techo: no se cuentan los intentos fallidos del SDK. Para mejorarlo,
`max_retries=0` en el cliente y reintento explícito en el arnés.
"""

from __future__ import annotations

# Copiados de scripts/eval_llm_judge.py (src no importa de scripts): 2 $ / 10 $
# por millón de tokens de entrada / salida.
INPUT_PRICE_PER_TOKEN = 2.00 / 1_000_000
OUTPUT_PRICE_PER_TOKEN = 10.00 / 1_000_000


def cost_of_usage(usage: dict) -> float:
    """Precio de una llamada a partir de su `usage` (vivo o guardado en caché)."""
    return (
        usage["input_tokens"] * INPUT_PRICE_PER_TOKEN
        + usage["output_tokens"] * OUTPUT_PRICE_PER_TOKEN
    )


class BudgetExceededError(RuntimeError):
    """La siguiente llamada podría superar el tope de gasto."""


class BudgetGuard:
    def __init__(self, cap_usd: float = 5.0, initial_call_estimate_usd: float = 0.01) -> None:
        self.cap_usd = cap_usd
        self.spent_usd = 0.0
        self.live_calls = 0
        self.failed_calls = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self._estimate_usd = initial_call_estimate_usd
        self._observed = False

    def check_can_call(self) -> None:
        if self.spent_usd + self._estimate_usd > self.cap_usd:
            raise BudgetExceededError(
                f"gastado {self.spent_usd:.4f} $ + siguiente llamada "
                f"~{self._estimate_usd:.4f} $ superaría el tope de {self.cap_usd} $"
            )

    def record_usage(self, usage: dict) -> float:
        """Suma una llamada en vivo y devuelve su coste."""
        inp, out = usage["input_tokens"], usage["output_tokens"]
        cost = cost_of_usage(usage)
        self.input_tokens += inp
        self.output_tokens += out
        self.spent_usd += cost
        self.live_calls += 1
        # La estimación es la llamada más cara vista; la inicial solo vale
        # hasta la primera observación.
        self._estimate_usd = cost if not self._observed else max(self._estimate_usd, cost)
        self._observed = True
        return cost

    def record_failure(self) -> None:
        """Un fallo no trae `usage`: se suma la estimación conservadora."""
        self.spent_usd += self._estimate_usd
        self.failed_calls += 1
