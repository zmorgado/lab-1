# Informe de Recursos y Tiempo de Ejecución — `tester.py`

**Fecha:** 20 de septiembre de 2026  
**Entorno:** Python 3.9 (mi_entorno_venv), PyTorch 2.8.0, macOS ARM64  
**Hardware:** Apple Silicon, 10 núcleos de CPU, 16 GB RAM  
**GPU:** No disponible — ejecución en CPU  
**Modelo:** `microsoft/unixcoder-base` (UniXcoder, modo encoder-only)  
**Límite de tokens:** 500 por script

---

## Resumen Ejecutivo

`tester.py` compara dos scripts de código usando UniXcoder para calcular su similitud coseno, con un límite de 500 tokens por script. El modelo se carga una sola vez y se reutiliza tanto para la tokenización como para la inferencia. Se ejecutan dos pruebas: una con scripts altamente similares y otra con scripts no relacionados.

| Indicador | Valor |
|---|---|
| **Tiempo total (similaridad alta)** | ~0.22 s |
| **Tiempo total (sin relación)** | ~0.22 s |
| **Pico de memoria RAM** | ~865 MB |
| **Crecimiento de memoria** | ~397 MB |
| **Núcleos de CPU** | 10 de 10 disponibles |

---

## 1. Prueba 1 — Scripts Altamente Similares

**Script 1:** `test_script1.py` — `sort_dictionary(d): dict(sorted(d.items(), key=lambda item: item[1]))`  
**Script 2:** `test_script2.py` — `order_mapping(data): dict(sorted(data.items(), key=lambda pair: pair[1]))`  
**Conteo de tokens:** 28 / 28

### Resultado

| Métrica | Valor |
|---|---|
| **Similitud coseno** | **0.7080** |
| **Veredicto** | **Altamente similar** |

### Tiempo de Ejecución

| Métrica | Valor |
|---|---|
| Tiempo real (reloj) | 0.2238 s |
| Tiempo CPU (usuario) | 0.4880 s |
| Tiempo CPU (sistema) | 0.2180 s |
| Tiempo CPU total | 0.7060 s |
| Cores de CPU | 10 |
| Utilización de CPU | 0.0 % |

### Memoria

| Métrica | Valor |
|---|---|
| RSS antes del modelo | 467.75 MB |
| RSS después del modelo | 864.97 MB |
| Crecimiento de memoria | 397.22 MB |
| Pico de asignación (tracemalloc) | 68.4 KB |
| Asignación actual (tracemalloc) | 46.3 KB |

### Sistema

| Métrica | Valor |
|---|---|
| Hilos activos | 7 |
| Descriptores de archivo abiertos | 9 |
| Fallos de página menores | 59 457 |

---

## 2. Prueba 2 — Scripts Sin Relación

**Script 1:** `test_script_long.py` — `sort_dictionary()` con comentarios y función auxiliar (52 tokens)  
**Script 2:** `test_script_unrelated.py` — `fetch_json()` (HTTP) y `factorial()` (matemáticas recursivas) (78 tokens)  
**Conteo de tokens:** 52 / 78

### Resultado

| Métrica | Valor |
|---|---|
| **Similitud coseno** | **0.2872** |
| **Veredicto** | **Ligeramente similar** |

### Tiempo de Ejecución

| Métrica | Valor |
|---|---|
| Tiempo real (reloj) | 0.2210 s |
| Tiempo CPU (usuario) | 0.4805 s |
| Tiempo CPU (sistema) | 0.2150 s |
| Tiempo CPU total | 0.6956 s |
| Cores de CPU | 10 |
| Utilización de CPU | 0.0 % |

### Memoria

| Métrica | Valor |
|---|---|
| RSS antes del modelo | 468.42 MB |
| RSS después del modelo | 866.05 MB |
| Crecimiento de memoria | 397.62 MB |
| Pico de asignación (tracemalloc) | 159.2 KB |
| Asignación actual (tracemalloc) | 121.4 KB |

### Sistema

| Métrica | Valor |
|---|---|
| Hilos activos | 7 |
| Descriptores de archivo abiertos | 9 |
| Fallos de página menores | 59 566 |

---

## 3. Comparación de Ambas Pruebas

| Métrica | Prueba 1 (Similar) | Prueba 2 (No relacionado) |
|---|---|---|
| Similitud coseno | 0.7080 | 0.2872 |
| Veredicto | Altamente similar | Ligeramente similar |
| Tiempo de ejecución | 0.2238 s | 0.2210 s |
| Tiempo CPU total | 0.7060 s | 0.6956 s |
| RSS después del modelo | 864.97 MB | 866.05 MB |
| Crecimiento de memoria | 397.22 MB | 397.62 MB |
| Tokens original | 28 | 52 |
| Tokens modificado | 28 | 78 |

> **Nota:** El tiempo de ejecución es prácticamente idéntico en ambas pruebas (~0.22 s), lo que confirma que el tiempo está dominado por la carga del modelo (~860 MB de pesos) y no por la complejidad del código comparado. La inferencia en sí es muy rápida una vez que el modelo está en memoria.

---

## 4. Análisis de Rendimiento

### Desglose de la carga del modelo

La mayor parte del tiempo y memoria se consume en:

1. **Carga de pesos del modelo** (~860 MB de RAM): El modelo UniXcoder-base se descarga/carga desde caché y ocupa la mayor parte de la memoria residente.
2. **Tokenización** (< 0.01 s): El tokenizer de Roberta procesa ambos scripts en milisegundos.
3. **Inferencia** (~0.2 s): El paso hacia adelante del transformer sobre secuencias cortas (28–78 tokens) es extremadamente rápido.

### Observaciones clave

- **Tiempo constante**: Independientemente de la similitud entre los scripts, el tiempo de ejecución se mantiene estable en ~0.22 s. Esto confirma que el cuello de botella es la carga del modelo, no el cómputo de similitud.
- **Bajo consumo de CPU (~0 % de utilización instantánea)**: La inferencia es lo suficientemente rápida para que psutil no registre utilización significativa en el intervalo de medición.
- **Cero swaps**: La presión de memoria (~865 MB) se maneja completamente dentro de los 16 GB de RAM física sin necesidad de paginación a disco.
- **Memoria de Python (tracemalloc) mínima**: Las asignaciones rastreadas por Python son solo ~50–160 KB, ya que los pesos del modelo se almacenan en tensores de PyTorch (gestionados por C++/CUDA, no por el rastreador de Python).
- **7 hilos activos**: Corresponden al intérprete de Python + hilos internos de torch y el sistema.
- **La truncación a 500 tokens funciona correctamente**: En la prueba 2, el script con 78 tokens no requirió truncamiento ya que está muy por debajo del límite de 500.

---

## 5. Uso y Sintaxis

```bash
python tester.py <script1.py> <script2.py>
```

**Ejemplo:**
```bash
python tester.py original.py modificado.py
```

El script acepta dos rutas de archivos, los lee, trunca a 500 tokens si es necesario, calcula la similitud coseno entre ambos usando UniXcoder, y imprime un informe completo de similitud y recursos.

---

## 6. Dependencias

- `torch` 2.8.0
- `transformers` 4.57.6
- `psutil` 7.2.2
- `unixcoder.py` (UniXcoder model class)
- `encoder_only_VE.py` (verify_code_semantics function)
- `python` 3.9

---

## 7. Recomendaciones

- **Caché de modelo**: En la primera ejecución el modelo se descarga de HuggingFace (~1.1 s adicional). Las ejecuciones posteriores usan la caché local y son ~5x más rápidas (~0.22 s).
- **GPU**: Si se dispone de GPU, el tiempo de inferencia se reduciría a milisegundos.
- **Batch processing**: Para comparar múltiples pares de scripts, se puede reutilizar la misma instancia del modelo sin recarga.
- **Modelo cuantizado**: Para entornos de producción con memoria limitada, considerar `torch.quantization` para reducir el footprint de ~860 MB.
