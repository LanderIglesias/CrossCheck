# Evaluación de CrossCheck (Fase 10): plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Medir dónde se rompen los dos checkers de CrossCheck (reglas y juez LLM) con casos reales difíciles (reexpresiones XBRL con causa leída en el filing, pares etiquetados a ciegas) y errores inyectados, por separado, con curva de sensibilidad, estabilidad del juez y coste, sin pasar de 5 $.

**Architecture:** Paquete nuevo `src/crosscheck/evaluation/` con piezas puras y testeadas (métricas, presupuesto, detector de reexpresiones, generador de mutaciones, agregación). Scripts `scripts/eval_phase10_*.py` que las orquestan. Todo lo que hace falta para reproducir (casos congelados, causas citadas, etiquetas a ciegas, predicciones, resultados) se commitea en `eval/phase10/`; nada se escribe en `claims` ni `gold_labels`. El juez gana un parámetro `repeat` en su clave de caché y devuelve el `usage` de las llamadas en vivo.

**Tech Stack:** Python 3, pydantic, psycopg (Postgres local vía docker-compose), anthropic SDK (`claude-sonnet-5`), pytest, `dashboard/index.html` estático.

**Spec:** `docs/superpowers/specs/2026-10-29-evaluacion-crosscheck-design.md` (léela entera antes de empezar cualquier tarea).

## Global Constraints

- Tope de **5 $** de API. Cuenta cada llamada en vivo, incluidos reintentos y fallos; los aciertos de caché no cuentan. Al llegar al tope, el script para y guarda lo que lleve.
- Antes de la ejecución completa hay una pasada piloto, y el usuario ve el coste real por llamada. **Puesto de control humano.**
- El total previsto queda por debajo de **~3,5 $**. La estabilidad son **60 pares × 5 repeticiones = 300 llamadas**, mitad mutados y mitad reales (con reexpresiones incluidas).
- Fuente real (A) e inyectada (B) **siempre por separado**: no hay ninguna cifra que las combine, ni en `results.json`, ni en el README, ni en el dashboard.
- Las mutaciones y las reexpresiones son `Claim` en memoria. **Nunca** se escriben en `claims` ni en `gold_labels`.
- Un caso real entra solo si su causa se ha citado literalmente del filing **y** el usuario ha revisado la cita (`user_reviewed: true`).
- Causas: `restatement`, `recast_discontinued_ops`, `stock_split`, `error`. El gold es `discrepant`, salvo `stock_split`, que es `ambiguous`.
- El gold de toda mutación es `discrepant`. Tamaños: 0,3 %, 0,5 % − ε, 0,5 % + ε, 1 %, 2 %, 5 % y 10 %, con ε = 0,01 pp (`0.0049` / `0.0051`).
- Unidad: valor × 1.000 con la etiqueta de unidad intacta. Periodo: etiqueta del periodo correcto con el valor real del trimestre anterior o del acumulado.
- El arnés llama a `check_pair` / `judge_pair` con el par forzado, sin `group_by_metric_and_period`.
- Todas las cifras de la fuente A llevan intervalo de Wilson al 95 %, y se cuentan las causas raíz además de los pares.
- No se cambian ni los checkers, ni el prompt, ni el modelo del juez (`MODEL_ID = "claude-sonnet-5"`). Precios: los de `scripts/eval_llm_judge.py` (2 $ / 10 $ por millón de tokens de entrada / salida).
- Ningún número del README ni del dashboard se escribe a mano: todos salen de `eval/phase10/results.json` o `report.md`, generados por un script ejecutado.
- Tests con pytest en `tests/`. Ejecuta solo los tests afectados (`pytest tests/test_x.py`). `make lint` (ruff, black, mypy src scripts, bandit) limpio al final de cada tarea.
- Ningún commit incluye `.claude/skills/`, `.serena/`, `.claude/settings.local.json` ni `data/raw/` (que ya está ignorado).

## Review Focus

1. **Los IDs de claim cambian tras `make test` + `make seed`.** El test de migraciones recrea el esquema y los IDs son serial. Las etiquetas a ciegas se emparejan por una clave de contenido estable, no por id (test en Tarea 6).
2. **El caché de EDGAR no está en el repo y companyfacts crece.** Si se descarga de nuevo meses después, aparecen filings nuevos y cambian los candidatos. Los candidatos se congelan en `eval/phase10/restatement_candidates.json` y el arnés lee de ahí, no del caché (test en Tarea 4).
3. **Valores negativos (pérdida neta), cero y BPA pequeños en las mutaciones.** La diferencia relativa que ve `check_pair` tiene que ser exactamente el tamaño pedido, a ambos lados de 0,5 %. Un valor base 0 se salta y se cuenta (test en Tarea 7).
4. **Corte por presupuesto a mitad de ejecución.** Los resultados parciales se guardan con `"partial": true` y se muestran como parciales, nunca como completos (tests en Tareas 3 y 8).
5. **Un par de reexpresión sin causa revisada.** Se excluye y se cuenta. Nunca se le asigna `discrepant` por defecto (test en Tarea 5).

---

### Task 1: Métricas (Wilson, precisión y recall)

**Files:**
- Create: `src/crosscheck/evaluation/__init__.py` (vacío), `src/crosscheck/evaluation/metrics.py`
- Test: `tests/test_eval_metrics.py`

**Interfaces:**
- Produces:
  - `wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float]`, que devuelve `(0.0, 0.0)` si `n == 0`.
  - `precision_recall(pairs: list[tuple[str, str]], positive: str = "discrepant") -> dict`, donde `pairs` son tuplas `(predicted, gold)`. Devuelve `{"tp","fp","fn","tn","precision","recall","precision_ci","recall_ci","n"}`. Si un ratio no tiene denominador, el ratio es `None`, no 0.

- [ ] **Step 1: Write the failing tests**

```python
def test_wilson_known_value():
    lo, hi = wilson_interval(8, 10)
    assert round(lo, 3) == 0.490 and round(hi, 3) == 0.943

def test_wilson_empty():
    assert wilson_interval(0, 0) == (0.0, 0.0)

def test_precision_recall_counts_and_none_when_undefined():
    r = precision_recall([("discrepant","discrepant"), ("consistent","discrepant"), ("discrepant","consistent")])
    assert (r["tp"], r["fn"], r["fp"]) == (1, 1, 1)
    assert r["precision"] == 0.5 and r["recall"] == 0.5
    assert precision_recall([("consistent","consistent")])["recall"] is None
```

- [ ] **Step 2:** `pytest tests/test_eval_metrics.py -v`. Expected: FAIL (ImportError).
- [ ] **Step 3:** Implementa las dos funciones en `metrics.py`. Wilson con la fórmula estándar y stdlib `math`.
- [ ] **Step 4:** `pytest tests/test_eval_metrics.py -v`. Expected: PASS.
- [ ] **Step 5:** Commit: `git commit -m "Eval fase 10: métricas (Wilson, precisión/recall de discrepant)"`

---

### Task 2: Juez: clave de caché con repetición y `usage` de las llamadas en vivo

**Files:**
- Modify: `src/crosscheck/consistency/llm_judge.py` (`_cache_path`, `judge_pair`)
- Test: `tests/test_llm_judge.py` (añadir tests y reutilizar `_FakeClient` / `_FakeMessages`)

**Interfaces:**
- Produces:
  - `_cache_path(prompt: str, repeat: int = 0) -> Path`. Con `repeat == 0` da **exactamente** la ruta de hoy, para no invalidar el caché existente. Con `repeat > 0` aplica el hash a `prompt + f"\n#repeat={repeat}"`. Lo que se envía a la API sigue siendo el `prompt` sin cambios.
  - `is_cached(claim_a: Claim, claim_b: Claim | None, repeat: int = 0) -> bool`
  - `judge_pair_with_usage(claim_a, claim_b, repeat: int = 0) -> tuple[Prediction, dict | None]`. El `dict` es `{"input_tokens","output_tokens"}` si hubo llamada en vivo y `None` si salió del caché.
  - `judge_pair(claim_a, claim_b, repeat: int = 0) -> Prediction` delega en `judge_pair_with_usage`.

- [ ] **Step 1: Write the failing tests**
  - `test_repeat_zero_keeps_existing_cache_path`: `_cache_path(p) == _cache_path(p, 0)`, y además igual a `raw_dir/llm_cache/MODEL_ID/sha256(p).json`. Así un cambio que rompa el caché existente falla.
  - `test_repeat_uses_distinct_cache_and_same_prompt`: `repeat=1` y `repeat=2` dan rutas distintas entre sí y distintas de la de 0. Con el cliente falso, dos `judge_pair(..., repeat=1)` hacen 1 llamada y `repeat=2` hace otra. El `messages[0]["content"]` enviado no contiene `#repeat`.
  - `test_judge_pair_with_usage_live_then_cached`: la primera llamada devuelve `usage == {"input_tokens": 100, "output_tokens": 20}` y la segunda devuelve `None`.
- [ ] **Step 2:** `pytest tests/test_llm_judge.py -v`. Expected: los tres nuevos FAIL y los existentes PASS.
- [ ] **Step 3:** Implementa los cambios. `scripts/eval_llm_judge.py` sigue funcionando sin cambios.
- [ ] **Step 4:** `pytest tests/test_llm_judge.py tests/test_consistency_checker.py -v`. Expected: PASS.
- [ ] **Step 5:** Commit: `"Juez LLM: clave de caché por repetición (repeat=0 conserva el caché actual) y usage de llamadas en vivo"`

---

### Task 3: Control de presupuesto

**Files:**
- Create: `src/crosscheck/evaluation/budget.py`
- Test: `tests/test_eval_budget.py`

**Interfaces:**
- Consumes: los precios `_INPUT_PRICE_PER_TOKEN` y `_OUTPUT_PRICE_PER_TOKEN`. Cópialos a `budget.py` como constantes públicas `INPUT_PRICE_PER_TOKEN` y `OUTPUT_PRICE_PER_TOKEN` (`src` no importa de `scripts`) y deja un comentario que remita a `eval_llm_judge.py`.
- Produces:
  - `class BudgetExceededError(RuntimeError)`
  - `class BudgetGuard` con `__init__(self, cap_usd: float = 5.0, initial_call_estimate_usd: float = 0.01)`, `spent_usd: float`, `live_calls: int`, `failed_calls: int`, `input_tokens: int` y `output_tokens: int`.
    - `check_can_call() -> None` lanza `BudgetExceededError` si `spent_usd + next_call_estimate > cap_usd`. La estimación es la llamada más cara observada, o `initial_call_estimate_usd` mientras no haya ninguna. Así no se pasa del tope: se para antes.
    - `record_usage(usage: dict) -> float` devuelve el coste de esa llamada.
    - `record_failure() -> None` suma la estimación conservadora, porque un fallo no trae `usage`.
- Nota `ponytail:` en el módulo. Los reintentos internos del SDK de anthropic (por defecto 2) no se ven desde aquí: solo se factura la respuesta final, que es la que trae `usage`. El techo es que no se cuentan los intentos fallidos del SDK; para mejorarlo, `max_retries=0` en el cliente y reintento explícito en el arnés.

- [ ] **Step 1: Write the failing tests**
  - `test_stops_before_exceeding_cap`: con `cap_usd=0.01`, tras `record_usage({"input_tokens": 2000, "output_tokens": 200})` (0,006 $), `check_can_call()` lanza la excepción, porque 0,006 + 0,006 > 0,01.
  - `test_failure_counts_against_budget`: `record_failure()` sube `spent_usd` y `failed_calls`.
  - `test_cost_matches_pricing`: 1.000.000 de tokens de entrada da 2,0 $.
- [ ] **Step 2:** `pytest tests/test_eval_budget.py -v`. Expected: FAIL.
- [ ] **Step 3:** Implementa `budget.py`.
- [ ] **Step 4:** `pytest tests/test_eval_budget.py -v`. Expected: PASS.
- [ ] **Step 5:** Commit: `"Eval fase 10: BudgetGuard con tope de 5 $ que para antes de pasarse"`

---

### Task 4: Detector de reexpresiones y candidatos congelados

**Files:**
- Create: `src/crosscheck/evaluation/restatements.py`, `scripts/eval_phase10_detect_restatements.py`, `eval/phase10/restatement_candidates.json` (generado y commiteado)
- Test: `tests/test_eval_restatements.py`, `tests/fixtures/companyfacts_restatement.json` (fixture pequeño escrito a mano: un tag, dos filings con valores distintos para el mismo trimestre, un tercero con el mismo valor y un hecho de 9 meses que se ignora)

**Interfaces:**
- Consumes: `TAG_TO_CANONICAL_KEY` y `_normalize_unit` de `crosscheck.extraction.xbrl`; `fetch_company_facts(cik)` de `crosscheck.sources.edgar` (acierta en caché); `COMPANIES` de `scripts/extract_xbrl_claims.py`, que trae ticker y subject, y el CIK de `db/seed_companies.sql` (cópialo en el script como dict `ticker -> cik`).
- Produces:
  - `@dataclass(frozen=True) FilingValue(accession: str, form: str, filed: date, value: Decimal)`
  - `@dataclass(frozen=True) RestatementCandidate(ticker, cik, subject, tag, canonical_metric_key, unit, period, start: date, end: date, values: tuple[FilingValue, ...])`. `values` va ordenado por `filed`, con un `FilingValue` por accession; `unit` está normalizada.
  - `find_restatements(company_facts: dict, ticker: str, cik: str, subject: str, years: tuple[int, ...] = (2019, 2020)) -> list[RestatementCandidate]`. Un candidato por `(tag, unit, start, end)` con duración trimestral (80-100 días, las mismas constantes que `xbrl.py`), `end.year` en `years`, formularios `10-Q`/`10-K`, y ≥ 2 valores distintos.
  - `period_label(end: date) -> str` devuelve `f"FY{end.year}-Q{(end.month - 1) // 3 + 1}"`. DHR y GE cierran el año fiscal en diciembre; anótalo en el docstring.
  - `restatement_pairs(c: RestatementCandidate) -> list[tuple[FilingValue, FilingValue]]`: el primer valor publicado frente a cada valor posterior **distinto**.
  - `to_claim(c: RestatementCandidate, fv: FilingValue, document_id: int) -> Claim` con `extraction_method="automated_xbrl"`, `metric=tag` y `confidence=1.0`.
  - `dump_candidates(cands, path: Path) -> None` y `load_candidates(path: Path) -> list[RestatementCandidate]`, que hacen una ida y vuelta sin pérdida (Decimal como str, fechas ISO).

- [ ] **Step 1: Write the failing tests**
  - `test_detects_value_change_across_filings`: el fixture da 1 candidato con 2 valores distintos y `restatement_pairs` da 1 par.
  - `test_ignores_non_quarterly_and_out_of_range_years`
  - `test_period_label`: `period_label(date(2019, 6, 28)) == "FY2019-Q2"`.
  - `test_candidates_roundtrip(tmp_path)`: `load_candidates(dump(...)) == cands` (Review Focus 2).
- [ ] **Step 2:** `pytest tests/test_eval_restatements.py -v`. Expected: FAIL.
- [ ] **Step 3:** Implementa el módulo y el script. El script recorre las 5 empresas de `COMPANIES`, imprime el recuento por ticker y escribe `eval/phase10/restatement_candidates.json`.
- [ ] **Step 4:** `pytest tests/test_eval_restatements.py -v`. Expected: PASS.
- [ ] **Step 5:** `python scripts/eval_phase10_detect_restatements.py`. Expected: DHR 39, GE 30 y 0 en PPC, TRV y ADTN (el hallazgo de la spec). **Si no coincide, no ajustes filtros para cuadrar**: anota en el docstring del script la definición usada y la diferencia, y avisa al usuario.
- [ ] **Step 6:** Commit del código, el test, el fixture y `restatement_candidates.json`: `"Eval fase 10: detector de reexpresiones XBRL y candidatos congelados en eval/phase10"`

---

### Task 5: Causas verificadas en el filing (con puesto de control humano)

**Files:**
- Create: `scripts/eval_phase10_fetch_restating_filings.py`, `eval/phase10/restatement_causes.json`, y en `src/crosscheck/evaluation/restatements.py` el cargador de casos confirmados
- Modify: `src/crosscheck/labeling/protocol.md` (sección nueva: taxonomía de causas y gold de las reexpresiones)
- Test: `tests/test_eval_restatements.py`

**Interfaces:**
- Consumes: `fetch_submissions(cik)` (`filings.recent.accessionNumber` / `primaryDocument`) y `fetch_filing_document(cik, accession, primary_document)` de `edgar.py`; `extract_text(html)` de `crosscheck.ingest.filing_text`; Tarea 4.
- Produces:
  - Esquema de `restatement_causes.json`: `{"root_causes": [{"id": str, "cause": "restatement"|"recast_discontinued_ops"|"stock_split"|"error", "ticker": str, "source_accession": str, "source_document": str, "quote": str, "user_reviewed": bool, "covers": [{"tag": str, "period": str, "accession_a": str, "accession_b": str}]}]}`. Cada entrada de `covers` es un par concreto de `restatement_pairs`.
  - `@dataclass(frozen=True) RealCase(case_id: str, claim_a: Claim, claim_b: Claim, gold: Verdict, cause: str, root_cause_id: str)`
  - `load_confirmed_cases(candidates: list[RestatementCandidate], causes_path: Path) -> tuple[list[RealCase], dict]`. El `dict` lleva `{"excluded_no_cause": int, "excluded_unreviewed": int, "root_causes": int}`. El gold es `AMBIGUOUS` si `cause == "stock_split"` y `DISCREPANT` en el resto; un valor de `cause` fuera de las cuatro causas lanza `ValueError`.

- [ ] **Step 1: Write the failing tests**
  - `test_unreviewed_or_missing_cause_is_excluded_not_defaulted` (Review Focus 5): un par cubierto por una causa con `user_reviewed: false` y otro par sin cobertura no dan ningún `RealCase`, y los dos contadores valen 1.
  - `test_stock_split_gold_is_ambiguous`
  - `test_unknown_cause_raises`
- [ ] **Step 2:** `pytest tests/test_eval_restatements.py -v`. Expected: los nuevos FAIL.
- [ ] **Step 3:** Implementa `load_confirmed_cases`. El script, para cada accession posterior de los candidatos, descarga el documento principal y escribe en pantalla los pasajes (±400 caracteres) que contienen `recast`, `discontinued operation`, `retrospectively`, `restat`, `reverse stock split` o `as adjusted`, con su desplazamiento de carácter. Solo lee; no escribe en el JSON.
- [ ] **Step 4:** `pytest tests/test_eval_restatements.py -v`. Expected: PASS.
- [ ] **Step 5 (Claude):** ejecuta el script, lee los pasajes y redacta `restatement_causes.json`. La `quote` es literal del texto extraído, `user_reviewed: false` en todas y cada par va asignado a una causa raíz. Los pares cuya causa no aparezca en el texto se quedan fuera de `covers`. Se esperan unas 5-10 causas raíz; no se fuerza ese número.
- [ ] **Step 6 — PUESTO DE CONTROL:** enseña al usuario cada causa raíz con su cita, su accession y el número de pares que cubre. El usuario pone `user_reviewed: true` en las que acepta. No sigas a la Tarea 8 sin esto.
- [ ] **Step 7:** Añade a `protocol.md` la taxonomía de causas, la regla `stock_split` → `ambiguous` y la exigencia de una cita revisada.
- [ ] **Step 8:** Commit: `"Eval fase 10: causas de reexpresión citadas del filing y revisadas, taxonomía en protocol.md"`

---

### Task 6: Exportación a ciegas de pares sin etiquetar (con puesto de control humano)

**Files:**
- Create: `src/crosscheck/evaluation/blind.py`, `scripts/eval_phase10_export_blind.py`, `eval/phase10/blind_pairs.csv`
- Test: `tests/test_eval_blind.py`

**Interfaces:**
- Consumes: `load_all_claims()` y `load_all_gold_labels()` de `scripts/eval_consistency_checker.py`; `group_by_metric_and_period`.
- Produces:
  - `claim_key(c: Claim) -> str`: une con `|` subject, canonical_metric_key, period, extraction_method, metric, value, unit, qualifier y speaker. No usa el id (Review Focus 1).
  - `pair_key(a: Claim, b: Claim) -> str`: los dos `claim_key` ordenados y unidos con `" || "`, para que el orden de los claims no importe.
  - `unlabeled_pairs(claims: list[Claim], gold: dict[frozenset[int], str]) -> list[tuple[Claim, Claim]]`: los pares de dos claims que genera la misma lógica de emparejamiento que `generate_predictions`, con document_id distinto y sin gold. Los singletons quedan fuera, porque `unsupported` es trivial para ambos checkers.
  - `BLIND_COLUMNS`: `pair_key, subject, canonical_metric_key, period, a_metric, a_value, a_unit, a_qualifier, a_speaker, a_extraction_method`, lo mismo con `b_*`, y después `verdict, rationale, labeled_by`. **Sin predicciones de ningún checker.**
  - `load_blind_labels(path: Path, claims: list[Claim]) -> list[tuple[Claim, Claim, Verdict, str]]`: vuelve a emparejar por `pair_key` y salta las filas sin `verdict`, que se cuentan aparte.

- [ ] **Step 1: Write the failing tests**
  - `test_pair_key_ignores_ids_and_order`: los mismos claims con otros `id` y en otro orden dan la misma clave.
  - `test_export_has_no_prediction_columns`: ninguna columna contiene `rule`, `llm`, `pred` ni `rationale_` de un checker.
  - `test_labeled_pair_excluded`: un par que ya está en `gold` no se exporta.
- [ ] **Step 2:** `pytest tests/test_eval_blind.py -v`. Expected: FAIL.
- [ ] **Step 3:** Implementa el módulo y el script (`make db-up` y `make seed` antes). Filas ordenadas por `pair_key`.
- [ ] **Step 4:** `pytest tests/test_eval_blind.py -v`. Expected: PASS.
- [ ] **Step 5:** Ejecuta el script. Expected: ≥ 8 filas (las 8 de PPC de la Fase 4 y las de la Fase 8).
- [ ] **Step 6 — PUESTO DE CONTROL:** el usuario rellena `verdict`, `rationale` y `labeled_by` siguiendo `protocol.md`, sin ver predicciones. No etiquetes tú.
- [ ] **Step 7:** Commit: `"Eval fase 10: exportación a ciegas de pares sin etiquetar, emparejados por contenido"`

---

### Task 7: Generador de mutaciones con semilla

**Files:**
- Create: `src/crosscheck/evaluation/mutations.py`
- Test: `tests/test_eval_mutations.py`

**Interfaces:**
- Consumes: `check_pair`, `TOLERANCE_PCT`; `_find_quarterly_fact` y `TAG_TO_CANONICAL_KEY` de `xbrl.py`.
- Produces:
  - `class MutationType(StrEnum)`: `VALUE = "value"`, `UNIT_X1000 = "unit_x1000"`, `PERIOD_PREV = "period_prev_quarter"` y `PERIOD_YTD = "period_ytd"`.
  - `VALUE_SIZES: tuple[Decimal, ...] = (Decimal("0.003"), Decimal("0.0049"), Decimal("0.0051"), Decimal("0.01"), Decimal("0.02"), Decimal("0.05"), Decimal("0.10"))`
  - `@dataclass(frozen=True) NeighborValues(prev_quarter: Decimal | None, ytd: Decimal | None)`
  - `neighbor_values(company_facts: dict, canonical_metric_key: str, quarter_accession: str) -> NeighborValues`. Localiza el hecho trimestral del 10-Q con `_find_quarterly_fact` y, con el tag de ese canonical key, busca:
    - el trimestre anterior: un hecho de 80-100 días cuyo `end` es el `start` base − 1 día;
    - el acumulado: mismo `end`, más de 100 días.

    Para cada periodo toma el primer valor publicado. Devuelve `None` donde no haya hecho, y en el acumulado de un Q1.
  - `@dataclass(frozen=True) Mutation(mutation_id: str, base_pair_key: str, type: MutationType, size: Decimal | None, direction: int | None, claim_a: Claim, claim_b: Claim)`. `gold` es siempre `DISCREPANT` y no se guarda como campo.
  - `generate_mutations(base_pairs: list[tuple[Claim, Claim]], neighbors: dict[str, NeighborValues], seed: int) -> tuple[list[Mutation], dict[str, int]]`. El `dict` lleva los motivos de salto: `zero_base`, `no_neighbor` y `neighbor_within_tolerance`.
  - `dump_mutations(muts, path)` / `load_mutations(path)` en JSON. El arnés guarda el artefacto en `eval/phase10/mutations.json`.

- [ ] **Step 1: Write the failing tests**
  - `test_value_mutation_hits_exact_relative_diff`: para valores base `Decimal("3000000000")`, `Decimal("0.72")` y `Decimal("-125400000")` (pérdida), y para cada tamaño y dirección, la diferencia relativa de `check_pair` cae dentro de ε/10 del tamaño, `0.0049` da `CONSISTENT` y `0.0051` da `DISCREPANT` (Review Focus 3).
  - `test_zero_base_is_skipped_and_counted`
  - `test_unit_mutation_multiplies_by_1000_keeps_unit_label`
  - `test_period_mutation_uses_neighbor_value_and_correct_label`: `claim_b.period == claim_a.period` y `claim_b.value == neighbors[...].prev_quarter`.
  - `test_same_seed_same_output_different_seed_differs`
  - `test_neighbor_values_from_fixture`: con `tests/fixtures/companyfacts_restatement.json` ampliado con un trimestre anterior y un acumulado.
- [ ] **Step 2:** `pytest tests/test_eval_mutations.py -v`. Expected: FAIL.
- [ ] **Step 3: Implementa.** El ancla es `claim_a.value` y la mutación sustituye el valor de `claim_b`; el resto de campos de `claim_b` no cambian. El algoritmo de valor, que no se deduce de las firmas, es este:

```python
# Con max(|a|,|b'|) como denominador (checker.py), ambas fórmulas dan diferencia relativa = s exacta:
# abajo: b' = a * (1 - s)   -> |a - b'| / |a|  = s
# arriba: b' = a / (1 - s)  -> |a - b'| / |b'| = s
# direction ~ random.Random(seed) (independiente por mutation_id); cuantiza b' con
# precisión suficiente para que el error de redondeo relativo sea < ε/10.
```

  Periodo: si `|vecino − a| / max ≤ TOLERANCE_PCT`, salta el caso (`neighbor_within_tolerance`), porque es indetectable por definición. `mutation_id` = hash corto de `(base_pair_key, type, size, direction)`.
- [ ] **Step 4:** `pytest tests/test_eval_mutations.py -v`. Expected: PASS.
- [ ] **Step 5:** Commit: `"Eval fase 10: generador de mutaciones con semilla (valor, unidad ×1000, periodo desplazado)"`

---

### Task 8: Arnés, agregación, piloto y ejecución completa (con puesto de control humano)

**Files:**
- Create: `src/crosscheck/evaluation/report.py`, `scripts/eval_phase10_run.py`, `eval/phase10/predictions.jsonl`, `eval/phase10/results.json`, `eval/phase10/report.md`, `eval/phase10/mutations.json`
- Test: `tests/test_eval_report.py`

**Interfaces:**
- Consumes: todo lo anterior. `load_all_claims` / `load_all_gold_labels`, `COMPANIES` (subject a accession del 10-Q) y `fetch_company_facts` para `neighbor_values`.
- Produces:
  - Fila de `predictions.jsonl` (un `dict` por línea): `{"item_id", "source": "real_restatement"|"real_blind"|"real_consistent_control"|"injected"|"stability", "checker": "rules"|"llm", "repeat": int, "gold": str, "predicted": str|None, "rationale": str, "cause": str|None, "root_cause_id": str|None, "mutation_type": str|None, "size": str|None, "live": bool, "cost_usd": float, "error": str|None}`.
  - `summarize(rows: list[dict], budget: dict, partial: bool) -> dict`. Claves de primer nivel: `real` (por checker: `precision_recall` de restatement y blind, cada uno por separado y juntos dentro de `real`, desglose por `cause`, `root_causes`, n y Wilson), `injected` (por checker: recall por `mutation_type` × `size`), `false_alarms` (por checker: tasa de `discrepant` sobre los controles reales `consistent` sin mutar, con Wilson), `stability` (`pairs`, `repeats`, `flip_rate` = pares con algún cambio / pares, `modal_agreement`), `cost` (`live_calls`, `failed_calls`, tokens, `spent_usd` = pagado en esta ejecución, `evaluation_cost_usd` = coste de todas las llamadas, también las servidas de caché, `by_source.{real,injected}` con `cost_usd`, `detected` y `cost_per_detected_inconsistency`, `controls_spent_usd`, `stability_spent_usd`; Task 8c), `partial` y `seed`. **No existe ninguna clave que combine `real` e `injected`.**
  - `render_report(summary: dict) -> str`: tablas Markdown para `report.md`. La curva de reglas va con la nota de que es un escalón por construcción: 0,3 % y 0,5 % − ε son fallos esperados por diseño, no un hallazgo.
  - CLI: `python scripts/eval_phase10_run.py --count`, `--pilot N` y `--full`, con `--seed` (por defecto 20261030) y `--cap-usd` (por defecto 5.0).

- [ ] **Step 1: Write the failing tests**
  - `test_summary_never_mixes_sources`: no hay ninguna clave en ninguna profundidad que agregue filas con `source` de `real_*` e `injected` a la vez. Compruébalo construyendo filas y verificando los n de cada bloque.
  - `test_recall_by_type_and_size`
  - `test_false_alarm_rate_on_controls`
  - `test_stability_flip_rate`: 2 pares × 5 repeticiones, uno estable y otro con un cambio, dan `flip_rate == 0.5`.
  - `test_partial_flag_propagates_to_report` (Review Focus 4): `partial=True` hace que `render_report` empiece con un aviso de resultados parciales.
  - `test_cost_per_detected_inconsistency_none_when_zero_detected`
- [ ] **Step 2:** `pytest tests/test_eval_report.py -v`. Expected: FAIL.
- [ ] **Step 3:** Implementa `report.py` y el script. Prioridad de ejecución, para que un corte deje lo más valioso:
  1. Casos reales: los `RealCase` confirmados y las etiquetas a ciegas.
  2. Controles: pares gold `consistent` reales sin mutar.
  3. Mutaciones.
  4. Estabilidad.

  Las reglas se ejecutan siempre, porque no cuestan nada. Cada llamada al juez sigue este orden:
  1. Con `is_cached`, si es acierto de caché, no se pasa por el guard.
  2. Si no, `guard.check_can_call()`.
  3. Luego `judge_pair_with_usage`.
  4. Por último `record_usage`, o `record_failure` si hay `RuntimeError`, con la fila marcada `error`.

  Si salta `BudgetExceededError`, se escribe todo con `partial=True` y el código de salida es 0, con un aviso.

  Estabilidad: 30 mutaciones (estratificadas por tipo y tamaño con la semilla) y 30 reales (primero las reexpresiones confirmadas, hasta 30, y después controles), con `repeat` 1..5.

  `document_id` de los claims en memoria: enteros negativos únicos. Ni `check_pair` ni el prompt los usan.
- [ ] **Step 4:** `pytest tests/test_eval_report.py tests/test_eval_mutations.py tests/test_llm_judge.py -v`. Expected: PASS.
- [ ] **Step 5:** `python scripts/eval_phase10_run.py --count`. Imprime el número de pares base `consistent` elegibles (la spec pide contarlo aquí), las mutaciones previstas, los casos reales y las llamadas en vivo previstas con la estimación de la Fase 8 (0,0035 $). Si el total previsto supera ~3,5 $, reduce el número de pares base (elegidos con la semilla) y anótalo.
- [ ] **Step 6:** `python scripts/eval_phase10_run.py --pilot 10`. Expected: 10 llamadas en vivo como mucho, coste medio por llamada real y proyección del total.
- [ ] **Step 7 — PUESTO DE CONTROL:** enseña al usuario la salida de `--count` y `--pilot` (coste real por llamada y total proyectado). La ejecución completa necesita su visto bueno.
- [ ] **Step 8:** `python scripts/eval_phase10_run.py --full`. Expected: `spent_usd ≤ 5.0`, sin `partial` (o con `partial` declarado), y los tres artefactos escritos. Reejecutar `--full` cuesta 0 $ (todo en caché): verifícalo.
- [ ] **Step 9:** Commit de los artefactos de `eval/phase10/`, el código y los tests: `"Eval fase 10: arnés con tope de gasto, piloto y ejecución completa; resultados en eval/phase10"`

---

### Task 9: Dashboard

**Files:**
- Modify: `scripts/export_dashboard_data.py` (clave `"phase10_eval"`), `dashboard/index.html` (sección nueva), `dashboard/data.json` (regenerado)

**Interfaces:**
- Consumes: `eval/phase10/results.json` (Tarea 8). `export_dashboard_data.py` lo copia tal cual en `snapshot["phase10_eval"]`, o pone `None` si no existe. No calcula nada nuevo.

- [ ] **Step 1:** Añade la clave en el export y ejecútalo (`python scripts/export_dashboard_data.py`). Expected: `data.json` con `phase10_eval` igual a `results.json`. Compruébalo con `python -c "import json;a=json.load(open('dashboard/data.json'))['phase10_eval'];b=json.load(open('eval/phase10/results.json'));assert a==b"`.
- [ ] **Step 2:** Sección en `index.html`, siguiendo el estilo, los tokens y la forma de pintar del resto del archivo (léelo antes):
  - curva de sensibilidad: recall por tamaño, una serie por checker y tipos separados;
  - tabla de casos reales por causa con n e IC de Wilson;
  - falsas alarmas, estabilidad y coste.

  Real e inyectado van en bloques visualmente separados, con el aviso de parcial si `partial`. Antes de pintar el gráfico, carga la skill `dataviz`.
- [ ] **Step 3:** `python scripts/serve_dashboard.py` y verifícalo en el navegador renderizado (Chrome DevTools: snapshot y consola sin errores, también a ancho de móvil). Que compile no basta.
- [ ] **Step 4:** `impeccable` audit y critique de la sección; aplica lo material.
- [ ] **Step 5:** Commit: `"Dashboard: sección de evaluación fase 10 (curva de sensibilidad, casos reales, estabilidad, coste)"`

---

### Task 10: README

**Files:**
- Modify: `README.md`. Pon `## Status: Phase 10 — evaluation` antes de la sección de la Fase 9 y `## Evaluation (Phase 10)` en la zona de "cómo ejecutar", junto a `## LLM-as-judge`.

- [ ] **Step 1:** Escribe la sección con:
  - metodología (fuentes A y B, verificación de causas con cita, etiquetado a ciegas, gold de mutaciones y de contrasplit);
  - tablas copiadas de `eval/phase10/report.md` (real e inyectado nunca en la misma tabla);
  - el escalón del checker de reglas explicado;
  - estabilidad, coste total y coste por inconsistencia detectada;
  - citas cualitativas del razonamiento del juez en casos reales, sin puntuarlas;
  - limitaciones: n pequeña e IC anchos, causas revisadas por una sola persona, reintentos internos del SDK, candidatos congelados en una fecha, período fiscal = calendario para DHR y GE;
  - reproducción: los comandos de `scripts/eval_phase10_*.py` y qué artefactos lee cada uno.

  Si hay `partial`, se dice arriba.
- [ ] **Step 2:** Verifica que cada número de la sección aparece en `report.md` o en `results.json`: haz `grep` de cada cifra.
- [ ] **Step 3:** `make lint`. Expected: limpio.
- [ ] **Step 4:** Commit: `"README: fase 10, evaluación (metodología, resultados por fuente, limitaciones, reproducción)"`

---

Al cerrar: `/code-review` nivel medio sobre la rama, `superpowers:verification-before-completion`, suite completa (`make test` y después `make seed`) y `superpowers:finishing-a-development-branch`.
