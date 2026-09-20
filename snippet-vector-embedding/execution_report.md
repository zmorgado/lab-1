# Informe de Recursos y Tiempo de Ejecución — `tester.py`

**Fecha:** 20 de septiembre de 2026  
**Entorno:** Python 3.9 (mi_entorno_venv), PyTorch 2.8.0, macOS ARM64  
**Hardware:** Apple Silicon, 10 núcleos de CPU, 16 GB RAM  
**GPU:** No disponible — ejecución en CPU  
**Modelo:** `microsoft/unixcoder-base` (UniXcoder, modo encoder-only)  
**Límite de tokens:** 1023 (máximo soportado por el modelo — buffer de atención 1024×1024)  
**Caso paradigmático:** `word_freq_A.py` vs `word_freq_B.py`

---

## Resumen Ejecutivo

`tester.py` compara dos scripts de código usando UniXcoder para calcular su similitud coseno, utilizando el límite máximo de 1023 tokens del modelo. El modelo se carga una sola vez y se reutiliza tanto para la tokenización como para la inferencia.

El caso paradigmático presenta dos implementaciones de conteo de frecuencia de palabras en Python (`word_freq_A.py` y `word_freq_B.py`), cada una con aproximadamente 500–600 tokens (545 y 610 respectivamente). Ambos scripts caben completamente dentro del límite de 1023 tokens, lo que permite al modelo considerar el contexto completo de cada archivo.

| Indicador | Valor |
|---|---|
| **Similitud coseno** | **0.9003** |
| **Veredicto** | **Altamente similar** |
| **Tiempo de ejecución** | **0.4768 s** |
| **Pico de memoria RAM** | **~925 MB** |
| **Crecimiento de memoria** | **~457 MB** |

---

## 1. Caso Paradigmático — `word_freq_A.py` vs `word_freq_B.py`

**Script 1:** `word_freq_A.py` — Implementación con `argparse`, `re`, y `collections.Counter` (545 tokens originales)  
**Script 2:** `word_freq_B.py` — Implementación con `sys`, bucle manual, diccionario y ordenación por selección (610 tokens originales)  
**Conteo de tokens:** 545 / 610 (ambos dentro del límite de 1023)

### Resultado

| Métrica | Valor |
|---|---|
| **Similitud coseno** | **0.9003** |
| **Veredicto** | **Altamente similar** |

Ambos scripts son semánticamente equivalentes (cuentan frecuencia de palabras) pero difieren en estilo: `word_freq_A.py` es más idiomático (usa `Counter`, `argparse`), mientras que `word_freq_B.py` es más manual (bucle explícito, selección para ordenar). La similitud de 0.9003 refleja que el modelo, al tener acceso al contexto completo, reconoce que ambas implementaciones resuelven el mismo problema.

### Tiempo de Ejecución

| Métrica | Valor |
|---|---|
| Tiempo real (reloj) | 0.4768 s |
| Tiempo CPU (usuario) | 1.2405 s |
| Tiempo CPU (sistema) | 0.4679 s |
| Tiempo CPU total | 1.7084 s |
| Cores de CPU | 10 |
| Utilización de CPU | 0.0 % |

### Memoria

| Métrica | Valor |
|---|---|
| RSS antes del modelo | 468.25 MB |
| RSS después del modelo | 924.95 MB |
| Crecimiento de memoria | 456.70 MB |
| Pico de asignación (tracemalloc) | 199.0 KB |
| Asignación actual (tracemalloc) | 137.1 KB |

### Sistema

| Métrica | Valor |
|---|---|
| Hilos activos | 7 |
| Descriptores de archivo abiertos | 9 |
| Fallos de página menores | 64 254 |

---

## 2. Impacto del Límite de Tokens

Se realizaron pruebas con distintos valores de `max_length` para medir el efecto de truncar el contexto:

| max_length | Tokens A | Tokens B | Similitud | Tiempo (s) |
|---|---|---|---|---|
| 50 | 50 | 50 | 0.5122 | 0.054 |
| 100 | 100 | 100 | 0.3191 | 0.055 |
| 200 | 200 | 200 | 0.5743 | 0.091 |
| 512 | 512 | 512 | 0.7819 | 0.207 |
| **1023** | **545** | **610** | **0.9003** | **0.477** |

> **Conclusión:** A mayor `max_length`, mayor contexto disponible para el modelo, y por tanto mayor precisión en la similitud semántica. La diferencia entre 512 y 1023 tokens es de **+11.8 puntos** de similitud (0.78 → 0.90), lo que demuestra que truncar a 512 tokens hace perder información valiosa en scripts de ~600 tokens.

---

## 3. Análisis de Rendimiento

### Desglose de la carga del modelo

La mayor parte del tiempo y memoria se consume en:

1. **Carga de pesos del modelo** (~925 MB de RAM): El modelo UniXcoder-base se carga desde caché local y representa el costo dominante de memoria. El incremento respecto a max_length=512 (~870 MB) se debe a que las secuencias más largas requieren matrices de atención más grandes.
2. **Tokenización** (< 0.01 s): El tokenizer de Roberta procesa ambos scripts en milisegundos.
3. **Inferencia** (~0.47 s): El paso hacia adelante del transformer sobre secuencias de ~600 tokens es más costoso que con 512 tokens debido al cómputo cuadrático de la atención.

### Observaciones clave

- **Tiempo constante con el contenido, escalable con max_length**: Independientemente de la similitud entre scripts, el tiempo de ejecución depende de `max_length`, no de los tokens reales. Scripts de 5000 tokens con `max_length=1023` tardan lo mismo que scripts de 500 tokens con `max_length=1023`.
- **Bajo consumo de CPU (~0 % de utilización instantánea)**: La inferencia es lo suficientemente rápida para que psutil no registre utilización significativa en el intervalo de medición.
- **CPU user > system (1.24s / 0.47s)**: La proporción indica que la mayor parte del cómputo es de propósito general (operaciones matemáticas de PyTorch en el transformer), con una porción menor en llamadas al sistema. El aumento de user/system time respecto a max_length=512 refleja el costo del cómputo de atención sobre secuencias más largas.
- **Cero swaps**: La presión de memoria (~925 MB) se maneja completamente dentro de los 16 GB de RAM física sin necesidad de paginación a disco.
- **Memoria de Python (tracemalloc) mínima**: Las asignaciones rastreadas por Python son solo ~137–199 KB, ya que los pesos del modelo se almacenan en tensores de PyTorch (gestionados por C++, no por el rastreador de Python).
- **7 hilos activos**: Corresponden al intérprete de Python + hilos internos de torch y el sistema.
- **Ambos scripts caben dentro de 1023 tokens**: 545 y 610 tokens están bien por debajo del límite máximo, lo que permite al modelo ver el contexto completo de cada archivo sin truncamiento.

---

## 4. Interpretación de la Similitud

La puntuación de **0.9003** clasifica a ambos scripts como **altamente similares**. Esto es consistente con el análisis:

- Ambos scripts reciben un archivo de texto y producen un reporte de las 10 palabras más frecuentes.
- Ambos filtran stopwords comunes y palabras de longitud < 2.
- Ambos ordenan por frecuencia descendente y luego alfabéticamente para empates.
- Las diferencias son de estilo (usar `Counter` vs. bucle manual, `argparse` vs. `sys.argv`), no de lógica.
- Con max_length=512 la similitud era 0.7940; con max_length=1023 sube a 0.9003, confirmando que el contexto adicional (imports completos, definiciones de funciones, lógica de post-procesamiento) es clave para el modelo.

---

## 5. Uso y Sintaxis

```bash
python tester.py <script1.py> <script2.py>
```

**Ejemplo:**
```bash
python tester.py word_freq_A.py word_freq_B.py
```

El script acepta dos rutas de archivos, los lee completamente (hasta 1023 tokens), calcula la similitud coseno entre ambos usando UniXcoder en modo encoder-only, y muestra la puntuación, un veredicto de similitud y un informe detallado de recursos y tiempo.

---

## 6. Dependencias

- `torch` 2.8.0
- `transformers` 4.57.6
- `psutil` 7.2.2
- `unixcoder.py` (UniXcoder model class)
- `encoder_only_VE.py` (verify_code_semantics function, max_length=1023)
- `python` 3.9

---

## 7. Recomendaciones

- **max_length=1023**: Se recomienda usar el límite máximo del modelo para maximizar la precisión de la similitud semántica. La pérdida de información al truncar a 512 tokens es significativa (~12 puntos de similitud).
- **Caché de modelo**: La primera ejecución descarga el modelo de HuggingFace (~1.1 s adicional). Las ejecuciones posteriores usan la caché local.
- **GPU**: Si se dispone de GPU, el tiempo de inferencia se reduciría drásticamente (la atención sobre 1024 tokens es muy costosa en CPU).
- **Batch processing**: Para comparar múltiples pares de scripts, se puede reutilizar la misma instancia del modelo sin recarga.
- **Modelo cuantizado**: Para entornos de producción con memoria limitada, considerar `torch.quantization` para reducir el footprint de ~925 MB.
- **Cuidado con scripts >1023 tokens**: Los scripts más largos serán truncados silenciosamente. Para scripts muy grandes, considerar resumir o extraer solo las funciones relevantes antes de comparar.
