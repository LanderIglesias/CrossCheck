# Ejecuciones de la Fase 10 (gasto de API)

Cada fila es una ejecución que hizo llamadas en vivo al juez LLM. Los aciertos de caché no cuestan.

| Ejecución | Fecha | Comando | Llamadas en vivo | Coste |
|---|---|---|---|---|
| Piloto | 2026-10-30 | `--pilot 10` | 10 | 0,0371 $ |
| 1 | 2026-10-30 | `--full --skip-stability` | 346 | 1,3035 $ |
| 2 | 2026-11-02 | `--full` | 363 | 1,3338 $ |
| **Total pagado en la Fase 10** | | | **719** | **2,6744 $** |

Además, el plan reutiliza entradas de la caché pagadas en la Fase 8 (2026-09-11) por un valor de
**0,2189 $**. Coste de la evaluación = 2,6744 $ + 0,2189 $ = **2,8933 $** (cada clave de caché se
cuenta una vez; `evaluation_cost_usd` en `results.json`).

El tope de 5 $ es acumulado entre ejecuciones y se controló a mano pasando `--cap-usd` = 5 − gastado
hasta entonces (Ruling 13). Tras la ejecución 2 quedaban 2,3256 $. La regeneración del informe sin
llamadas en vivo (`--full --cap-usd 2.32`, caché completa) gasta 0 $ y por eso `report.md` muestra
"Pagado en esta ejecución: 0.0000 $"; el gasto real por ejecución es el de esta tabla.
