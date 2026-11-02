"""Agregación y informe de la evaluación de la Fase 10.

Las filas de predicciones se agregan por fuente: real (reexpresiones y etiquetas a ciegas),
controles reales `consistent` e inyectadas. Ningún bloque combina fuente real e inyectada: sus
n responden a preguntas distintas (precisión sobre casos naturales frente a sensibilidad a errores
sintéticos). La estabilidad y el coste son aparte porque no miden acierto.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from crosscheck.evaluation.metrics import precision_recall, wilson_interval

_REAL_SOURCES = ("real_restatement", "real_blind")
_CHECKERS = ("rules", "llm")


def _scored(rows: list[dict]) -> list[dict]:
    """Rows that produced a prediction (an errored judge call has predicted None)."""
    return [r for r in rows if r["predicted"] is not None]


def _errors(rows: list[dict]) -> int:
    return sum(1 for r in rows if r["error"])


def _pr(rows: list[dict]) -> dict:
    pr = precision_recall([(r["predicted"], r["gold"]) for r in _scored(rows)])
    return {**pr, "errors": _errors(rows)}


def _discrepant_rate(rows: list[dict]) -> dict:
    scored = _scored(rows)
    hits = sum(1 for r in scored if r["predicted"] == "discrepant")
    return {
        "n": len(scored),
        "hits": hits,
        "errors": _errors(rows),
        "rate": hits / len(scored) if scored else None,
        "ci": wilson_interval(hits, len(scored)),
    }


def _real_block(rows: list[dict]) -> dict:
    by_cause: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        if r["cause"]:
            by_cause[r["cause"]].append(r)
    return {
        "restatement": _pr([r for r in rows if r["source"] == "real_restatement"]),
        "blind": _pr([r for r in rows if r["source"] == "real_blind"]),
        "combined": _pr(rows),
        "by_cause": {c: _pr(rs) for c, rs in sorted(by_cause.items())},
        "root_causes": len({r["root_cause_id"] for r in rows if r["root_cause_id"]}),
    }


def _injected_block(rows: list[dict]) -> dict:
    cells: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for r in rows:
        cells[r["mutation_type"]][r["size"] or "n/a"].append(r)
    out: dict[str, dict[str, dict]] = {}
    for mtype, by_size in sorted(cells.items()):
        out[mtype] = {}
        for size, rs in sorted(by_size.items()):
            d = _discrepant_rate(rs)
            out[mtype][size] = {
                "n": d["n"],
                "detected": d["hits"],
                "recall": d["rate"],
                "recall_ci": d["ci"],
                "errors": d["errors"],
            }
    return out


def _stability(rows: list[dict]) -> dict:
    by_pair: dict[str, list[str]] = defaultdict(list)
    origin: dict[str, str] = {}
    for r in rows:
        if r["predicted"] is None:
            continue
        by_pair[r["item_id"]].append(r["predicted"])
        origin[r["item_id"]] = "injected" if r["mutation_type"] else "real"

    def stats(ids: list[str]) -> dict:
        flips = sum(1 for i in ids if len(set(by_pair[i])) > 1)
        modal = [Counter(by_pair[i]).most_common(1)[0][1] / len(by_pair[i]) for i in ids]
        return {
            "pairs": len(ids),
            "flip_rate": flips / len(ids) if ids else None,
            "modal_agreement": sum(modal) / len(modal) if modal else None,
        }

    ids = sorted(by_pair)
    # No pooled figure: real and injected pairs are never aggregated together.
    return {
        "repeats": max((len(v) for v in by_pair.values()), default=0),
        "errors": _errors(rows),
        "by_origin": {o: stats([i for i in ids if origin[i] == o]) for o in ("real", "injected")},
    }


def summarize(
    rows: list[dict],
    budget: dict,
    partial: bool,
    seed: int | None = None,
    skip_stability: bool = False,
) -> dict:
    main = [r for r in rows if r["source"] != "stability"]
    stab = [r for r in rows if r["source"] == "stability" and r["checker"] == "llm"]

    def of(checker: str, *sources: str) -> list[dict]:
        return [r for r in main if r["checker"] == checker and r["source"] in sources]

    llm_all = [r for r in rows if r["checker"] == "llm"]
    # One cache key is one paid call: a later row with a key already seen costs 0, so the first
    # row in plan order (real, controls, injected, stability) carries the cost. Rows without a
    # key (older artifacts) are summed as they are.
    seen: set[str] = set()
    charged: dict[int, float] = {}
    for r in llm_all:
        k = r.get("cache_key")
        charged[id(r)] = 0.0 if k in seen else r["cost_usd"]
        if k is not None:
            seen.add(k)

    def cost_of(sources: tuple[str, ...]) -> dict:
        rs = [r for r in llm_all if r["source"] in sources]
        cost_src = sum(charged[id(r)] for r in rs)
        det = sum(1 for r in rs if r["predicted"] == "discrepant" and r["gold"] == "discrepant")
        return {
            "cost_usd": cost_src,
            "detected": det,
            "cost_per_detected_inconsistency": cost_src / det if det else None,
        }

    spent = budget["spent_usd"]
    # Controls and blind pairs are different metrics but can be the same judge prompt (Ruling 15).
    blind_keys = {r.get("cache_key") for r in of("llm", "real_blind")} - {None}
    return {
        "controls_overlapping_blind": len(
            {r.get("cache_key") for r in of("llm", "real_consistent_control")} & blind_keys
        ),
        "real": {c: _real_block(of(c, *_REAL_SOURCES)) for c in _CHECKERS},
        "injected": {c: _injected_block(of(c, "injected")) for c in _CHECKERS},
        "false_alarms": {c: _discrepant_rate(of(c, "real_consistent_control")) for c in _CHECKERS},
        # Skipped is not zero: nothing was measured, so there is no flip rate.
        "stability": {"skipped": True} if skip_stability else _stability(stab),
        "cost": {
            "live_calls": budget["live_calls"],
            "failed_calls": budget["failed_calls"],
            "input_tokens": budget["input_tokens"],
            "output_tokens": budget["output_tokens"],
            "spent_usd": spent,
            # Every llm row, cache hits included, so the figure does not depend on what was
            # already cached when this run started; each cache key counted once.
            "evaluation_cost_usd": sum(charged.values()),
            "by_source": {"real": cost_of(_REAL_SOURCES), "injected": cost_of(("injected",))},
            "controls_spent_usd": cost_of(("real_consistent_control",))["cost_usd"],
            "stability_spent_usd": cost_of(("stability",))["cost_usd"],
        },
        "partial": partial,
        "seed": seed,
    }


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.1%}"


def _ci(ci: tuple[float, float], ratio: float | None) -> str:
    # precision_recall gives (0, 0) for an undefined ratio: printing it would look like a result.
    return "n/a" if ratio is None else f"[{ci[0]:.1%}, {ci[1]:.1%}]"


def _pr_row(name: str, m: dict) -> str:
    return (
        f"| {name} | {m['n']} (errores: {m['errors']}) | {_pct(m['precision'])} {_ci(m['precision_ci'], m['precision'])} "
        f"| {_pct(m['recall'])} {_ci(m['recall_ci'], m['recall'])} |"
    )


def render_report(summary: dict[str, Any]) -> str:
    out: list[str] = []
    if summary["partial"]:
        out += [
            "> **AVISO: resultados parciales.** La ejecución se cortó (tope de gasto) antes de "
            "completar todos los elementos previstos.",
            "",
        ]
    out += ["# Evaluación de CrossCheck, Fase 10", ""]
    if summary["seed"] is not None:
        out += [f"Semilla: {summary['seed']}", ""]

    out += ["## A. Casos reales (precisión y recall de `discrepant`, IC de Wilson 95 %)", ""]
    for c in _CHECKERS:
        blk = summary["real"][c]
        out += [
            f"### {c} (causas raíz: {blk['root_causes']})",
            "",
            "| Subconjunto | n | Precisión | Recall |",
            "|---|---|---|---|",
            _pr_row("reexpresiones", blk["restatement"]),
            _pr_row("a ciegas", blk["blind"]),
            _pr_row("juntos (solo reales)", blk["combined"]),
            *(_pr_row(f"causa: {cause}", m) for cause, m in blk["by_cause"].items()),
            "",
        ]

    out += ["## B. Errores inyectados (recall de `discrepant`), aparte de A", ""]
    out += [
        "La curva de reglas es un escalón por construcción (tolerancia del 0,5 %): los fallos en "
        "0,3 % y 0,5 % - e son esperados por diseño, no un hallazgo.",
        "",
    ]
    for c in _CHECKERS:
        out += [
            f"### {c}",
            "",
            "| Tipo | Tamaño | n | Recall | IC 95 % |",
            "|---|---|---|---|---|",
        ]
        for mtype, by_size in summary["injected"][c].items():
            for size, cell in by_size.items():
                out.append(
                    f"| {mtype} | {size} | {cell['n']} (errores: {cell['errors']}) | {_pct(cell['recall'])} "
                    f"| {_ci(cell['recall_ci'], cell['recall'])} |"
                )
        out.append("")

    out += [
        "## C. Falsas alarmas (controles reales `consistent` sin mutar)",
        "",
        "| Checker | n | Tasa de `discrepant` | IC 95 % |",
        "|---|---|---|---|",
    ]
    for c in _CHECKERS:
        fa = summary["false_alarms"][c]
        out.append(
            f"| {c} | {fa['n']} (errores: {fa['errors']}) | {_pct(fa['rate'])} | {_ci(fa['ci'], fa['rate'])} |"
        )

    st = summary["stability"]
    out += ["", "## D. Estabilidad del juez LLM (real e inyectado por separado)", ""]
    if st.get("skipped"):
        out.append("Estabilidad omitida (--skip-stability): no se midió.")
    else:
        out += [
            f"Repeticiones: {st['repeats']}, errores: {st['errors']}",
            "",
            "| Origen | Pares | Tasa de cambio | Acuerdo con la moda |",
            "|---|---|---|---|",
        ]
        for origin, o in st["by_origin"].items():
            out.append(
                f"| {origin} | {o['pairs']} | {_pct(o['flip_rate'])} | {_pct(o['modal_agreement'])} |"
            )
    co = summary["cost"]
    out += [
        "",
        "## E. Coste",
        "",
        f"Llamadas en vivo: {co['live_calls']}, fallidas: {co['failed_calls']}, "
        f"tokens: {co['input_tokens']} entrada / {co['output_tokens']} salida",
        "",
        f"Coste de la evaluación (todas las llamadas, también las servidas de caché, "
        f"a precio de cuando se pagaron): {co['evaluation_cost_usd']:.4f} $ "
        f"(controles: {co['controls_spent_usd']:.4f} $, estabilidad: "
        f"{co['stability_spent_usd']:.4f} $)",
        "",
        f"Pagado en esta ejecución: {co['spent_usd']:.4f} $",
        "",
        "| Fuente | Coste | Detectadas | Coste por inconsistencia detectada |",
        "|---|---|---|---|",
    ]
    for src, c in co["by_source"].items():
        cpd = c["cost_per_detected_inconsistency"]
        out.append(
            f"| {src} | {c['cost_usd']:.4f} $ | {c['detected']} "
            f"| {'n/a' if cpd is None else f'{cpd:.4f} $'} |"
        )
    out.append("")
    return "\n".join(out)
