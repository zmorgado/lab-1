# Informe de Recursos y Tiempo de Ejecución — `tester.py`

**Fecha:** 20 de septiembre de 2026  
**Entorno:** Python 3.9 (mi_entorno_venv), PyTorch 2.8.0, macOS ARM64  
**Hardware:** Apple Silicon, 10 núcleos de CPU, 16 GB RAM  
**GPU:** No disponible — ejecución en CPU

---

## Resumen Ejecutivo

`tester.py` carga el modelo **UniXcoder-base** (`microsoft/unixcoder-base`) desde HuggingFace Hub y calcula puntuaciones de similitud coseno entre un snippet de código consulta y 11 candidatos, evaluando su relación semántica.

| Indicador | Valor |
|---|---|
| **Tiempo total de ejecución** | ~5,5 – 7,3 segundos |
| **Pico de memoria RAM** | ~1,3 GB |
| **Instrucciones ejecutadas** | ~56,5 mil millones |
| **Núcleos de CPU utilizados** | 1 de 10 (~15 %) |

---

## 1. Tiempo de Ejecución

### Desglose por fase

| Fase | Duración estimada | Descripción |
|---|---|---|
| Importación de módulos | ~1,6 s | Carga de `torch`, `transformers`, `unixcoder` y dependencias |
| Descarga del modelo (HTTPS) | ~1,13 s | Lectura de pesos vía SSL desde HuggingFace Hub |
| Carga desde caché local | ~0,07 s | Deserialización de tensores desde disco |
| Tokenización | ~0,10 s | Codificación de la consulta y 11 snippets con `RobertaTokenizer` |
| Inferencia (paso hacia adelante) | ~1,08 s | Dos pases del modelo: consulta + embeddings de código |
| Pos-procesamiento | ~0,05 s | Normalización L2, multiplicación de matrices, ordenación e impresión |

> **Nota:** En la primera ejecución el modelo se descarga de HuggingFace (~1,13 s). En ejecuciones posteriores usa la caché local y el tiempo total se reduce a ~2–3 s.

### Métricas detalladas

| Métrica | Valor |
|---|---|
| Tiempo real (reloj) | 5,55 s |
| Tiempo de CPU (usuario) | 4,07 s |
| Tiempo de CPU (sistema) | 0,53 s |

---

## 2. Uso de Memoria

### Evolución del consumo de RAM

| Etapa | RSS (memoria residente) | Incremento |
|---|---|---|
| Antes de importar | 12,84 MB | — |
| Después de importar | 382,48 MB | +369,64 MB |
| Después de inferencia | 1 303,69 MB | +921,20 MB |
| **Pico máximo** | **~1 536 MB** | — |

### Detalles de asignación (tracemalloc)

| Métrica | Valor |
|---|---|
| Pico de asignaciones | 158 164 KB (~154,5 MB) |
| Asignaciones actuales | 128 798 KB (~125,8 MB) |

### Memoria virtual y fallos de página

| Métrica | Valor |
|---|---|
| Memoria virtual (VMS) | ~425 GB (espacio de direcciones, no físico) |
| Tamaño residente (RSS) | ~417 MB |
| Fallos de página menores | ~109 323 |
| Page faults | 35 |
| Swaps | 0 |

---

## 3. CPU y Recursos del Sistema

| Métrica | Valor |
|---|---|
| Núcleos de CPU disponibles | 10 |
| Utilización de CPU | ~15 % (inferencia monopuesto) |
| Hilos activos | 7 |
| Descriptores de archivo abiertos | 9 |
| Cambios de contexto voluntarios | 3 482 |
| Cambios de contexto involuntarios | 4 003 |

---

## 4. Estadísticas a Nivel de Instrucción

Mediciones obtenidas con `/usr/bin/time -l`:

| Métrica | Valor |
|---|---|
| Instrucciones ejecutadas | 56 515 957 510 |
| Ciclos de reloj | 16 723 195 081 |
| Reclamaciones de página | 105 234 |
| CPI (ciclos por instrucción) | ~0,30 |

Un CPI de 0,30 indica una ejecución altamente eficiente, típica de operaciones matriciales intensivas delegadas a rutinas BLAS optimizadas.

---

## 5. Principales Consumidores de Tiempo (cProfile)

| Función | Tiempo (s) | Categoría |
|---|---|---|
| `_ssl._SSLSocket.read` | 1,129 | Red — descarga del modelo |
| `torch._C._nn.linear` | 0,699 | Inferencia — multiplicación de matrices |
| `transformers.import_utils.fetch__all__` | 0,250 | Importaciones diferidas |
| `torch._C._nn.scaled_dot_product_attention` | 0,219 | Mecanismo de atención |
| `torch._C._nn.gelu` | 0,102 | Función de activación |
| `_ssl._SSLSocket.do_handshake` | 0,074 | Negociación TLS |
| `torch.serialization.load_tensor` | 0,070 | Deserialización de pesos |

---

## 6. Puntuaciones de Similitud Obtenidas

| Ranking | Puntuación | Etiqueta | Interpretación |
|---|---|---|---|
| 1 | **0,7873** | NIVEL 4 | Ordena por clave (estructura relacionada, criterio distinto) |
| 2 | **0,6738** | NIVEL 1 | Clon casi idéntico (nombres de variables distintos) |
| 3 | **0,5469** | NIVEL 2 | Misma funcionalidad, distinta sintaxis (`itemgetter`) |
| 4 | **0,4733** | NIVEL 5 | Mismo concepto, estructura de datos diferente |
| 5 | **0,3935** | NIVEL 7 | Invertir diccionario (misma estructura, operación distinta) |
| 6 | **0,3589** | NIVEL 6 | Filtrar por valor (sin ordenación) |
| 7 | **0,3299** | NIVEL 3 | Ordenación manual (misma lógica, algoritmo distinto) |
| 8 | **0,2141** | NIVEL 8 | Invertir palabras (manipulación de cadenas, no relacionado) |
| 9 | **0,2058** | NIVEL 11 | Factorial recursivo (matemáticas, no relacionado) |
| 10 | **0,0790** | NIVEL 10 | Petición HTTP/JSON (completamente ajeno) |
| 11 | **-0,0159** | NIVEL 9 | Lectura de líneas de archivo (completamente ajeno) |

---

## 7. Observaciones y Cuellos de Botella

1. **La descarga del modelo domina el tiempo.** Las lecturas SSL representan ~1,13 s. Con pesos en caché, las ejecuciones posteriores son significativamente más rápidas.
2. **La memoria es el costo principal.** El modelo carga ~1 GB de pesos en RAM, y el tokenizador eleva el consumo de ~13 MB a ~1,3 GB.
3. **Inferencia limitada por CPU.** Sin GPU disponible, el paso hacia adelante se ejecuta en CPU y tarda ~1,08 s para una consulta contra 11 snippets.
4. **Baja utilización de CPU (~15 %).** Indica que la carga está dominada por E/S de red y que la inferencia es monopuesto.
5. **Cero swaps.** La presión de memoria se maneja completamente dentro de la RAM física.
6. **~56,5 mil millones de instrucciones.** Refleja las pesadas operaciones matriciales del encoder transformer, delegadas mayoritariamente a rutinas BLAS optimizadas.

---

## 8. Recomendaciones

- **Caché local de pesos del modelo** para evitar descargas HTTPS repetidas.
- **Usar GPU** si está disponible; reduciría el tiempo de inferencia de ~1 s a milisegundos.
- **Inferencia por lotes (batch)** si se procesan múltiples consultas, agrupando tokenización y pases del modelo.
- **Limitar hilos de torch** con `torch.set_num_threads()` para reducir sobrecarga de cambio de contexto.
- **Considerar cuantización del modelo** (`torch.quantization`) para reducir el consumo de memoria en entornos de producción.
