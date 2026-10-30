# Evaluación de CrossCheck: casos reales difíciles + errores inyectados

Fecha: 2026-10-29. Estado: aprobado por el usuario el 2026-10-30; siguiente paso, plan de implementación (superpowers:writing-plans).

## Intención y por qué

CrossCheck ya reporta accuracy de sus dos checkers (reglas, Fase 4; juez LLM, Fase 5) sobre 49
`gold_labels` humanas: 97,8 % ambos en la Fase 8. Ese número no dice casi nada: las etiquetas son
casi todas `consistent`/`unsupported`, solo hay 2 desacuerdos reales, y la precisión/recall de
`discrepant` — lo que CrossCheck existe para detectar — no se puede medir hoy.

Objetivo del usuario: poder contar CrossCheck a reclutadores y, sobre todo, a AI engineers senior
con algo que les sorprenda de verdad. La apuesta (mía, aceptada por el usuario): lo que impresiona
no es un porcentaje alto sino **saber exactamente dónde se rompe el sistema, con números**, y
hacerlo con la misma honestidad metodológica que la evaluación RAG de AI-Portfolio
(`backend/agents/rag_pdf_agent/eval/README.md` en ese repo: corrección a ciegas, sesgo del
corrector medido, limitaciones explícitas, reproducción).

## Qué se construye (decidido con el usuario)

Una mezcla de dos fuentes, **siempre reportadas por separado**:

### A. Casos reales difíciles: reexpresiones en XBRL

Hallazgo de exploración (2026-10-29) sobre `data/raw/edgar_cache/*.json` (companyfacts ya
descargados): para periodos 2019-2020 y los tags que CrossCheck ya extrae, hay **69 (tag, periodo)
con valores distintos según el filing que los publica**: 39 en Danaher (DHR), 30 en GE; 0 en
PPC, TRV, ADTN (y en AXP/HSY, también en caché). Ejemplos reales:

- DHR, ingresos Q2-2019: 5.156,6 M$ (10-Q 2019-07-18) vs 4.444,5 M$ (10-K 2020-02-21), −16 %.
  Hipótesis no verificada: reexpresión por operaciones discontinuadas (salida de Envista, 2019).
- GE, BPA diluido operaciones continuadas Q1-2020: 0,72 $ (10-Q 2020-04-29) → 0,70 $ (10-Q
  2021-04-27) → 5,63 $ (10-K 2022-02-11). Hipótesis no verificada: reexpresión pequeña + contrasplit
  1×8 de 2021.

Estos pares son "trampas reales": valores distintos que no son errores, sino cambios de definición
o de base. **Regla dura: la causa de cada caso se confirma leyendo el filing (texto del 10-K/10-Q
correspondiente) antes de etiquetarlo; un caso sin causa confirmada no entra** (fiabilidad: nunca
rellenar con lo plausible). Probablemente bastan unos pocos filings por empresa, porque una misma
reexpresión explica muchos (tag, periodo).

Más el **etiquetado a ciegas** de los pares que los checkers generan y nadie etiquetó (8 en PPC en
la Fase 4, más tras la Fase 8): se exportan sin las predicciones de los checkers y los etiqueta el
usuario siguiendo `src/crosscheck/labeling/protocol.md`.

### B. Errores inyectados (sintéticos, etiquetados como tales)

Sobre claims reales `consistent` ya etiquetados, se generan copias mutadas con error conocido:

- tamaño relativo: 0,3 %, 0,5 % (justo en la tolerancia de reglas), 1 %, 2 %, 5 %, 10 %;
- tipo: valor numérico alterado; unidad cambiada (×1.000, millones↔miles); periodo desplazado
  (trimestre vecino, Q vs acumulado).

Salida: **curva de sensibilidad** (recall de `discrepant` por tamaño y tipo) para cada checker,
y tasa de falsas alarmas sobre los pares reales `consistent` sin mutar. Las mutaciones **nunca se
escriben en `claims` ni `gold_labels`** (mismo principio que la Fase 4: la tabla "gold" solo
contiene verdad humana); viven en un artefacto de evaluación aparte, generado con semilla fija.

### Encima de A y B

- **Estabilidad del juez LLM**: repetir un subconjunto (~100 pares) 5 veces y medir la tasa de
  cambio de veredicto. Nota técnica: el caché actual de `llm_judge.py` es por hash del prompt
  (`_cache_path`), así que repetir daría siempre la respuesta cacheada; las repeticiones necesitan
  una clave de caché que incluya el índice de repetición (sin romper el caché existente).
- **Coste por inconsistencia detectada** y coste total real (tokens y $), como en la Fase 8.

## Etiquetado de las reexpresiones (mi decisión, revisable)

El conjunto de veredictos existente es `consistent | discrepant | unsupported | ambiguous`. Para
el par "original vs reexpresado" el gold es `discrepant` (la cifra cambió y señalarlo es el
trabajo del producto) más un campo de **causa** (`restatement`, `recast_discontinued_ops`,
`stock_split`, `error`). Excepción (decidida por el usuario el 2026-10-30): **un cambio de base
por contrasplit tiene gold `ambiguous`** (no comparable sin ajustar); un checker que lo marque
`discrepant` falla ese caso. Los checkers no emiten causa: el campo de causa se usa para
desglosar los resultados por tipo de caso, y la explicación del juez (su texto de razonamiento)
se cita de forma cualitativa en el README, sin puntuarla (no se cambia el juez). Esta taxonomía
de causas es nueva y se documenta en `protocol.md`.

## Resultado visible (decidido con el usuario)

1. **README**: sección nueva tipo "Phase 10 — evaluation", con metodología, tablas por fuente
   (real vs inyectado, nunca mezcladas), curva, estabilidad, coste, limitaciones y cómo reproducir.
2. **Dashboard** (`dashboard/index.html` + `data.json`, publicado en landerworks.com/crosscheck):
   sección nueva con la curva de sensibilidad y la tabla de casos reales; los datos salen de
   `scripts/export_dashboard_data.py` (nada inventado, como el resto del dashboard). Con UI:
   pasar `impeccable` (audit/critique) antes de dar por terminado.

## Presupuesto (decidido con el usuario: "lo justo para que sea profesional")

Tope **5 $** de API, con corte automático en el script (si se alcanza, para y guarda lo que
lleve). Estimación sobre el coste real de la Fase 8 (~0,0035 $/llamada): ~1.000 llamadas ≈ 3,6 $.
Antes de la ejecución completa, una pasada pequeña de prueba para medir el coste real por llamada
y enseñárselo al usuario.

## Objetivos, no objetivos, anti-objetivos

- Objetivos: precisión/recall de `discrepant` medibles; casos reales difíciles con causa
  verificada; curva de sensibilidad; estabilidad del juez; coste; reproducible desde el repo.
- No objetivos: mejorar los checkers (si la evaluación encuentra fallos, se reportan; arreglarlos
  es otro proyecto), ampliar a más empresas, cambiar el modelo del juez.
- Anti-objetivos (fracaso aunque funcione): mezclar sintético y real en una sola cifra; un caso
  real con causa supuesta y no leída en el filing; escribir datos mutados en tablas "gold"; pasar
  del tope de gasto; números del README/dashboard que no salgan de un script ejecutado.

## Restricciones

- Postgres local (docker-compose del repo); el juez es `claude-sonnet-5` vía `llm_judge.py`.
- Tests con pytest, como el resto del repo (`tests/`); un test por pieza no trivial (generador de
  mutaciones con semilla, clave de caché de repeticiones, detector de reexpresiones).
- Mantener README y dashboard sincronizados con lo medido.

## Decisiones tras la revisión (mías salvo que se indique)

1. **Checker de reglas y la curva.** Es determinista con `TOLERANCE_PCT = 0,5 %`, así que su
   curva es un escalón por construcción: los puntos 0,3 % y 0,5 % verifican el límite diseñado, no
   son un hallazgo, y el README lo dice así. El valor de la curva está en el juez LLM y en el
   contraste entre ambos. El 0,5 % exacto se genera como 0,5 % ± ε a cada lado para no depender
   del redondeo.
2. **Cómo llegan las mutaciones a los checkers.** El arnés construye objetos `Claim` en memoria y
   llama directamente a `check_pair` / `judge_pair` con el par forzado, sin pasar por
   `group_by_metric_and_period` (si no, un periodo desplazado nunca se emparejaría). El gold de
   toda mutación es `discrepant`:
   - valor alterado: mismo periodo y unidad, valor distinto;
   - unidad: se multiplica el valor por 1.000 sin cambiar la etiqueta de unidad, que es el error
     real de "millones leídos como miles";
   - periodo: el par lleva la etiqueta del periodo correcto pero el valor real del trimestre
     vecino o del acumulado.
3. **Las reexpresiones no se escriben en la BD.** Se construyen como `Claim` en memoria desde los
   companyfacts del caché, uno por filing (`extraction_method='automated_xbrl'`, y en el
   artefacto de evaluación el número de accession de origen). No se tocan ni `claims` ni
   `gold_labels`.
4. **Verificación de causas.** La hace Claude: descarga de EDGAR (con el cliente con caché del
   repo) el filing que reexpresa y cita literalmente el pasaje que lo explica. El usuario revisa
   esas citas antes de que el caso entre. Lo esperable es que los 69 (tag, periodo) se reduzcan a
   unas 5-10 causas raíz. Con una n tan pequeña, todas las cifras de la fuente A llevan intervalo
   de confianza de Wilson al 95 % y se cuentan las causas raíz además de los pares.
5. **Reparto del presupuesto.**
   - El número de pares `consistent` reales elegibles se cuenta al planificar.
   - La estabilidad usa 60 pares × 5 repeticiones (300 llamadas): mitad mutados y mitad reales,
     incluidas las reexpresiones.
   - Las mutaciones se ajustan para que el total previsto quede por debajo de ~3,5 $.
6. **El tope de 5 $ cuenta cada llamada en vivo, reintentos y fallos incluidos.** Los aciertos de
   caché no cuentan. El script acumula el coste real a partir de los `usage` de cada respuesta.

## Lo que queda al builder

Nombres de scripts y ficheros, formato del artefacto de mutaciones (JSON/CSV), cómo se presenta
la exportación a ciegas para etiquetar, el diseño visual concreto de la sección del dashboard,
y el número exacto de pares base para las mutaciones dentro del tope de gasto.
