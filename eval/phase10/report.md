# Evaluación de CrossCheck, Fase 10

Semilla: 20261030

## A. Casos reales (precisión y recall de `discrepant`, IC de Wilson 95 %)

### rules (causas raíz: 16)

| Subconjunto | n | Precisión | Recall |
|---|---|---|---|
| reexpresiones | 63 (errores: 0) | 60.0% [45.5%, 73.0%] | 100.0% [87.5%, 100.0%] |
| a ciegas | 42 (errores: 0) | 0.0% [0.0%, 56.2%] | n/a n/a |
| juntos (solo reales) | 105 (errores: 0) | 56.2% [42.3%, 69.3%] | 100.0% [87.5%, 100.0%] |
| causa: recast_discontinued_ops | 27 (errores: 0) | 100.0% [87.5%, 100.0%] | 100.0% [87.5%, 100.0%] |
| causa: rounding | 18 (errores: 0) | n/a n/a | n/a n/a |
| causa: stock_split | 18 (errores: 0) | 0.0% [0.0%, 17.6%] | n/a n/a |

### llm (causas raíz: 16)

| Subconjunto | n | Precisión | Recall |
|---|---|---|---|
| reexpresiones | 63 (errores: 0) | 60.0% [45.5%, 73.0%] | 100.0% [87.5%, 100.0%] |
| a ciegas | 42 (errores: 0) | 0.0% [0.0%, 79.3%] | n/a n/a |
| juntos (solo reales) | 105 (errores: 0) | 58.7% [44.3%, 71.7%] | 100.0% [87.5%, 100.0%] |
| causa: recast_discontinued_ops | 27 (errores: 0) | 100.0% [87.5%, 100.0%] | 100.0% [87.5%, 100.0%] |
| causa: rounding | 18 (errores: 0) | n/a n/a | n/a n/a |
| causa: stock_split | 18 (errores: 0) | 0.0% [0.0%, 17.6%] | n/a n/a |

## B. Errores inyectados (recall de `discrepant`), aparte de A

La curva de reglas es un escalón por construcción (tolerancia del 0,5 %): los fallos en 0,3 % y 0,5 % - e son esperados por diseño, no un hallazgo.

### rules

| Tipo | Tamaño | n | Recall | IC 95 % |
|---|---|---|---|---|
| period_prev_quarter | n/a | 29 (errores: 0) | 100.0% | [88.3%, 100.0%] |
| period_ytd | n/a | 20 (errores: 0) | 100.0% | [83.9%, 100.0%] |
| unit_x1000 | n/a | 41 (errores: 0) | 100.0% | [91.4%, 100.0%] |
| value | 0.003 | 41 (errores: 0) | 0.0% | [0.0%, 8.6%] |
| value | 0.0049 | 41 (errores: 0) | 0.0% | [0.0%, 8.6%] |
| value | 0.0051 | 41 (errores: 0) | 100.0% | [91.4%, 100.0%] |
| value | 0.01 | 41 (errores: 0) | 100.0% | [91.4%, 100.0%] |
| value | 0.02 | 41 (errores: 0) | 100.0% | [91.4%, 100.0%] |
| value | 0.05 | 41 (errores: 0) | 100.0% | [91.4%, 100.0%] |
| value | 0.10 | 41 (errores: 0) | 100.0% | [91.4%, 100.0%] |

### llm

| Tipo | Tamaño | n | Recall | IC 95 % |
|---|---|---|---|---|
| period_prev_quarter | n/a | 29 (errores: 0) | 100.0% | [88.3%, 100.0%] |
| period_ytd | n/a | 20 (errores: 0) | 100.0% | [83.9%, 100.0%] |
| unit_x1000 | n/a | 41 (errores: 0) | 51.2% | [36.5%, 65.7%] |
| value | 0.003 | 41 (errores: 0) | 51.2% | [36.5%, 65.7%] |
| value | 0.0049 | 41 (errores: 0) | 65.9% | [50.5%, 78.4%] |
| value | 0.0051 | 41 (errores: 0) | 65.9% | [50.5%, 78.4%] |
| value | 0.01 | 41 (errores: 0) | 75.6% | [60.7%, 86.2%] |
| value | 0.02 | 41 (errores: 0) | 82.9% | [68.7%, 91.5%] |
| value | 0.05 | 41 (errores: 0) | 97.6% | [87.4%, 99.6%] |
| value | 0.10 | 41 (errores: 0) | 100.0% | [91.4%, 100.0%] |

## C. Falsas alarmas (controles reales `consistent` sin mutar)

| Checker | n | Tasa de `discrepant` | IC 95 % |
|---|---|---|---|
| rules | 41 (errores: 0) | 2.4% | [0.4%, 12.6%] |
| llm | 41 (errores: 0) | 2.4% | [0.4%, 12.6%] |

## D. Estabilidad del juez LLM (real e inyectado por separado)

Repeticiones: 5, errores: 0

| Origen | Pares | Tasa de cambio | Acuerdo con la moda |
|---|---|---|---|
| real | 30 | 0.0% | 100.0% |
| injected | 30 | 3.3% | 99.3% |

## E. Coste

Llamadas en vivo: 0, fallidas: 0, tokens: 0 entrada / 0 salida

Coste de la evaluación (todas las llamadas, también las servidas de caché, a precio de cuando se pagaron): 3.0504 $ (controles: 0.1456 $, estabilidad: 1.1037 $)

Pagado en esta ejecución: 0.0000 $

| Fuente | Coste | Detectadas | Coste por inconsistencia detectada |
|---|---|---|---|
| real | 0.3806 $ | 27 | 0.0141 $ |
| injected | 1.4205 $ | 291 | 0.0049 $ |
