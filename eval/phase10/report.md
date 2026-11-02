# Evaluación de CrossCheck, Fase 10

Semilla: 20261030

## A. Casos reales (precisión y recall de `discrepant`, IC de Wilson 95 %)

### rules (causas raíz: 16)

| Subconjunto | n | Precisión | Recall |
|---|---|---|---|
| reexpresiones | 63 (errores: 0) | 60.0% [45.5%, 73.0%] | 100.0% [87.5%, 100.0%] |
| a ciegas | 38 (errores: 0) | 0.0% [0.0%, 56.2%] | n/a n/a |
| juntos (solo reales) | 101 (errores: 0) | 56.2% [42.3%, 69.3%] | 100.0% [87.5%, 100.0%] |
| causa: recast_discontinued_ops | 27 (errores: 0) | 100.0% [87.5%, 100.0%] | 100.0% [87.5%, 100.0%] |
| causa: rounding | 18 (errores: 0) | n/a n/a | n/a n/a |
| causa: stock_split | 18 (errores: 0) | 0.0% [0.0%, 17.6%] | n/a n/a |

### llm (causas raíz: 16)

| Subconjunto | n | Precisión | Recall |
|---|---|---|---|
| reexpresiones | 63 (errores: 0) | 60.0% [45.5%, 73.0%] | 100.0% [87.5%, 100.0%] |
| a ciegas | 38 (errores: 0) | 0.0% [0.0%, 79.3%] | n/a n/a |
| juntos (solo reales) | 101 (errores: 0) | 58.7% [44.3%, 71.7%] | 100.0% [87.5%, 100.0%] |
| causa: recast_discontinued_ops | 27 (errores: 0) | 100.0% [87.5%, 100.0%] | 100.0% [87.5%, 100.0%] |
| causa: rounding | 18 (errores: 0) | n/a n/a | n/a n/a |
| causa: stock_split | 18 (errores: 0) | 0.0% [0.0%, 17.6%] | n/a n/a |

## B. Errores inyectados (recall de `discrepant`), aparte de A

La curva de reglas es un escalón por construcción (tolerancia del 0,5 %): los fallos en 0,3 % y 0,5 % - e son esperados por diseño, no un hallazgo.

### rules

| Tipo | Tamaño | n | Recall | IC 95 % |
|---|---|---|---|---|
| period_prev_quarter | n/a | 27 (errores: 0) | 100.0% | [87.5%, 100.0%] |
| period_ytd | n/a | 18 (errores: 0) | 100.0% | [82.4%, 100.0%] |
| unit_x1000 | n/a | 38 (errores: 0) | 100.0% | [90.8%, 100.0%] |
| value | 0.003 | 39 (errores: 0) | 0.0% | [0.0%, 9.0%] |
| value | 0.0049 | 38 (errores: 0) | 0.0% | [0.0%, 9.2%] |
| value | 0.0051 | 38 (errores: 0) | 100.0% | [90.8%, 100.0%] |
| value | 0.01 | 39 (errores: 0) | 100.0% | [91.0%, 100.0%] |
| value | 0.02 | 38 (errores: 0) | 100.0% | [90.8%, 100.0%] |
| value | 0.05 | 38 (errores: 0) | 100.0% | [90.8%, 100.0%] |
| value | 0.10 | 38 (errores: 0) | 100.0% | [90.8%, 100.0%] |

### llm

| Tipo | Tamaño | n | Recall | IC 95 % |
|---|---|---|---|---|
| period_prev_quarter | n/a | 27 (errores: 0) | 100.0% | [87.5%, 100.0%] |
| period_ytd | n/a | 18 (errores: 0) | 100.0% | [82.4%, 100.0%] |
| unit_x1000 | n/a | 38 (errores: 0) | 50.0% | [34.8%, 65.2%] |
| value | 0.003 | 39 (errores: 0) | 51.3% | [36.2%, 66.1%] |
| value | 0.0049 | 38 (errores: 0) | 65.8% | [49.9%, 78.8%] |
| value | 0.0051 | 38 (errores: 0) | 65.8% | [49.9%, 78.8%] |
| value | 0.01 | 39 (errores: 0) | 76.9% | [61.7%, 87.4%] |
| value | 0.02 | 38 (errores: 0) | 84.2% | [69.6%, 92.6%] |
| value | 0.05 | 38 (errores: 0) | 97.4% | [86.5%, 99.5%] |
| value | 0.10 | 38 (errores: 0) | 100.0% | [90.8%, 100.0%] |

## C. Falsas alarmas (controles reales `consistent` sin mutar)

| Checker | n | Tasa de `discrepant` | IC 95 % |
|---|---|---|---|
| rules | 39 (errores: 0) | 2.6% | [0.5%, 13.2%] |
| llm | 39 (errores: 0) | 2.6% | [0.5%, 13.2%] |

## D. Estabilidad del juez LLM (real e inyectado por separado)

Repeticiones: 5, errores: 0

| Origen | Pares | Tasa de cambio | Acuerdo con la moda |
|---|---|---|---|
| real | 30 | 0.0% | 100.0% |
| injected | 30 | 3.3% | 99.3% |

## E. Coste

Llamadas en vivo: 0, fallidas: 0, tokens: 0 entrada / 0 salida

Coste de la evaluación (todas las llamadas, también las servidas de caché, a precio de cuando se pagaron): 2.8933 $ (controles: 0.1001 $, estabilidad: 1.1037 $)

Pagado en esta ejecución: 0.0000 $

| Fuente | Coste | Detectadas | Coste por inconsistencia detectada |
|---|---|---|---|
| real | 0.3667 $ | 27 | 0.0136 $ |
| injected | 1.3228 $ | 271 | 0.0049 $ |
