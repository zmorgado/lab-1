# Informe de Recursos y Tiempo de Ejecución — `tester.py`

**Fecha:** 20 de septiembre de 2026  
**Entorno:** Python 3.9 (mi_entorno_venv), PyTorch 2.8.0, macOS ARM64  
**Hardware:** Apple Silicon, 10 núcleos de CPU, 16 GB RAM  
**GPU:** No disponible — ejecución en CPU  
**Modelo:** `microsoft/unixcoder-base` (UniXcoder, modo encoder-only)  
**Límite de tokens:** 500 por script  
**Caso paradigmático:** `word_freq_A.py` vs `word_freq_B.py`

---

## Resumen Ejecutivo

`tester.py` compara dos scripts de código usando UniXcoder para calcular su similitud coseno, con un límite de 500 tokens por script. El modelo se carga una sola vez y se reutiliza tanto para la tokenización como para la inferencia.

El caso paradigmático presenta dos implementaciones de conteo de frecuencia de palabras en Python (`word_freq_A.py` y `word_freq_B.py`), cada una con aproximadamente 500 tokens. Ambos scripts resuelven el mismo problema (frecuencia de palabras) con enfoques diferentes: el primero usa `Counter` y expresiones regulares, el segundo usa un bucle manual con diccionario y manipulación de cadenas.

| Indicador | Valor |
|---|---|
| **Similitud coseno** | **0.7940** |
| **Veredicto** | **Altamente similar** |
| **Tiempo de ejecución** | **0.2269 s** |
| **Pico de memoria RAM** | **~870 MB** |
| **Crecimiento de memoria** | **~402 MB** |

---

## 1. Caso Paradigmático — `word_freq_A.py` vs `word_freq_B.py`

**Script 1:** `word_freq_A.py` — Implementación con `argparse`, `re`, y `collections.Counter` (545 tokens originales, truncado a 500)  
**Script 2:** `word_freq_B.py` — Implementación con `sys`, bucle manual, diccionario y ordenación por selección (610 tokens originales, truncado a 500)  
**Conteo de tokens:** 545 / 610 (ambos truncados a 500)

### Resultado

| Métrica | Valor |
|---|---|
| **Similitud coseno** | **0.7940** |
| **Veredicto** | **Altamente similar** |

Ambos scripts son semánticamente equivalentes (cuentan frecuencia de palabras) pero difieren en estilo: `word_freq_A.py` es más idiomático (usa `Counter`, `argparse`), mientras que `word_freq_B.py` es más manual (bucle explícito, selección para ordenar). La similitud de 0.7940 refleja que la intención y estructura general son las mismas.

### Tiempo de Ejecución

| Métrica | Valor |
|---|---|
| Tiempo real (reloj) | 0.2269 s |
| Tiempo CPU (usuario) | 0.4887 s |
| Tiempo CPU (sistema) | 0.2215 s |
| Tiempo CPU total | 0.7102 s |
| Cores de CPU | 10 |
| Utilización de CPU | 0.0 % |

### Memoria

| Métrica | Valor |
|---|---|
| RSS antes del modelo | 468.30 MB |
| RSS después del modelo | 870.30 MB |
| Crecimiento de memoria | 402.00 MB |
| Pico de asignación (tracemalloc) | 66.2 KB |
| Asignación actual (tracemalloc) | 44.1 KB |

### Sistema

| Métrica | Valor |
|---|---|
| Hilos activos | 7 |
| Descriptores de archivo abiertos | 9 |
| Fallos de página menores | 59 821 |

---

## 2. Desglose de Fases

| Fase | Duración estimada | Descripción |
|---|---|---|
| Carga del modelo | ~0.15 s | UniXcoder-base desde caché local (~870 MB) |
| Tokenización | ~0.01 s | Codificación de ambos scripts con RobertaTokenizer |
| Truncación a 500 tokens | ~0.001 s | Corte de tokens excedentes |
| Inferencia (forward pass) | ~0.06 s | Dos pases del transformer (query + code embeddings) |
| Similitud coseno | ~0.005 s | Normalización L2 + multiplicación de matrices |
| Reporte | ~0.001 s | Formateo e impresión de resultados |

---

## 3. Análisis de Rendimiento

### Carga del modelo

La mayor parte del tiempo y memoria se consume en:

1. **Carga de pesos del modelo** (~870 MB de RAM): El modelo UniXcoder-base se carga desde caché local y representa el costo dominante de memoria.
2. **Tokenización** (< 0.01 s): El tokenizer de Roberta procesa ambos scripts (~500 tokens cada uno) en milisegundos.
3. **Inferencia** (~0.06 s): El paso hacia adelante del transformer sobre secuencias de ~500 tokens es muy rápido.

### Observaciones clave

- **Tiempo constante**: La ejecución se mantiene en ~0.23 s independientemente de la similitud entre scripts. El cuello de botella es la carga del modelo (~870 MB), no el cómputo de similitud.
- **Bajo consumo de CPU (~0 % de utilización instantánea)**: La inferencia es lo suficientemente rápida para que psutil no registre utilización significativa en el intervalo de medición.
- **CPU user > system**: La proporción 0.49s usuario / 0.22s sistema indica que la mayor parte del cómputo es de propósito general (operaciones matemáticas de PyTorch), con una porción menor en llamadas al sistema (gestión de memoria, E/S).
- **Cero swaps**: La presión de memoria (~870 MB) se maneja completamente dentro de los 16 GB de RAM física sin necesidad de paginación a disco.
- **Memoria de Python (tracemalloc) mínima**: Las asignaciones rastreadas por Python son solo ~44–66 KB, ya que los pesos del modelo se almacenan en tensores de PyTorch (gestionados por C++, no por el rastreador de Python).
- **7 hilos activos**: Corresponden al intérprete de Python + hilos internos de torch y el sistema.
- **Truncación efectiva**: Ambos scripts (~545 y ~610 tokens originales) fueron recortados a 500 tokens, demostrando que el mecanismo de límite funciona correctamente para scripts de tamaño moderado.
- **Alta similitud (0.7940)**: A pesar de que ambos scripts usan técnicas de programación distintas (declarativa vs. imperativa), UniXcoder reconoce que resuelven el mismo problema de conteo de frecuencia de palabras.

---

## 4. Interpretación de la Similitud

La puntuación de **0.7940** clasifica a ambos scripts como **altamente similares**. Esto es consistente con el análisis:

- Ambos scripts reciben un archivo de texto y producen un reporte de las 10 palabras más frecuentes.
- Ambos filtran stopwords comunes y palabras de longitud < 2.
- Ambos ordenan por frecuencia descendente y luego alfabéticamente para empates.
- Las diferencias son de estilo (usar `Counter` vs. bucle manual, `argparse` vs. `sys.argv`), no de lógica.

---

## 5. Uso y Sintaxis

```bash
python tester.py <script1.py> <script2.py>
```

**Ejemplo:**
```bash
python tester.py word_freq_A.py word_freq_B.py
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

- **Caché de modelo**: La primera ejecución descarga el modelo de HuggingFace (~1.1 s adicional). Las ejecuciones posteriores usan la caché local y toman ~0.23 s.
- **GPU**: Si se dispone de GPU, el tiempo de inferencia se reduciría a milisegundos.
- **Batch processing**: Para comparar múltiples pares de scripts, se puede reutilizar la misma instancia del modelo sin recarga.
- **Modelo cuantizado**: Para entornos de producción con memoria limitada, considerar `torch.quantization` para reducir el footprint de ~870 MB.
- **Tokens precisos**: El truncamiento actual reconstruye el texto desde tokens recortados, lo cual puede perder coherencia sintáctica al cortar a mitad de una función. Para scripts más largos, considerar truncar a nivel de función o línea completa.
