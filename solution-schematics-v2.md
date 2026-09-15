### Pipeline de Recuperación y Comparación de Código (v2)

Ejecución paso a paso del pipeline de recuperación y comparación de código, criterios de coincidencia explícitos en cada etapa, y verificación semántica basada en UniXcoder [47, 62].

---

#### Marco de Ejecución del Pipeline y Definiciones de Coincidencia

Para evitar confundir la estructura sintáctica con la semántica de ejecución, cada etapa aplica un criterio de coincidencia distinto [47, 62]:

* **Coincidencia Léxica (Etapa 3):** Coocurrencia de palabras clave y símbolos dentro del texto fuente, identificadores y metadatos del repositorio, indexados por la API de GitHub [47, 62]. Proporciona un *recall* grueso de candidatos, pero no evalúa similitud estructural ni funcional [47, 62]. Permite además interacción con el usuario para agregar tags adicionales que el sistema no haya considerado inicialmente [62].
* **Coincidencia Estructural (Etapa 4):** Congruencia en la geometría del árbol de sintaxis, tipos de nodo del AST (p. ej., `function_definition`, `call`, `lambda`) y relaciones padre-hijo [47, 62]. La similitud de AST garantiza una organización sintáctica similar, pero no implica una ejecución semántica idéntica [47, 62]. Garantiza snippets verosímiles y autocontenidos, aunque representa una instancia de riesgo de omisión si los umbrales se fijan de forma excesivamente estricta [62].
* **Coincidencia Semántica (Etapa 5):** Equivalencia funcional y conceptual de alto nivel entre fragmentos de código, medida mediante similitud coseno de vectores en el espacio latente continuo de 768 dimensiones de UniXcoder ($\mathbb{R}^{768}$) [47, 62]. Dos fragmentos de código pueden ser una coincidencia semántica total incluso sin superposición léxica superficial o con árboles de sintaxis estructuralmente distintos [47, 62].

---

#### Etapa 1 — Extracción del Snippet

**Script Fuente A:** *Ej.* `local_repository/utils/dictionary_helpers.py` [48, 63]  
**Método de Extracción:** Mediante un parser de AST (p. ej., Tree-sitter o el módulo `ast` nativo de Python), el script A se analiza para localizar construcciones estructurales de nivel superior [48, 63]. El snippet objetivo $a$ se aísla usando los límites de desplazamiento de bytes de su nodo (`start_byte` a `end_byte`) [48, 63].

**Snippet Objetivo Extraído $a$:**
```python
def rank_dictionary_by_value(input_dict, reverse_order=True):
    """Sort a Python dictionary by its values and return a new dictionary."""
    sorted_pairs = sorted(input_dict.items(), key=lambda item: item[1], reverse=reverse_order)
    return dict(sorted_pairs)
```

---

#### Etapa 2 — Extracción de Tags

Al analizar el snippet $a$ se obtienen sus descriptores conceptuales y funcionales centrales [49, 64]:

* **Nombre del Algoritmo:** Ordenamiento de diccionario / Ranking por valor [49, 64]
* **Estructura de Datos:** `dict` (mapa hash), lista de tuplas clave-valor [49, 64]
* **Patrón de Diseño / Paradigma:** Mapeo de función clave de orden superior (`lambda`) [49, 64]
* **Llamadas a Librería / API:** `sorted()`, `dict.items()`, `dict()` [49, 64]
* **Palabras Clave de Dominio:** Python, ranking por valor, ordenar diccionario [49, 64]

**Consultas de Búsqueda Ordenadas para la API de GitHub (`/search/code`):** [49, 64]
1. `python dict sort key lambda items` [50, 64]
2. `sorted dict.items key lambda value` [50, 64]
3. `def rank dict sorted language:python` [50, 64]

---

#### Etapa 3 — Búsqueda en GitHub (Recuperación Léxica de Candidatos)

**Ejecución de API:** `GET https://api.github.com/search/code?q=python+dict+sort+key+lambda+items+language:python` [50, 65]  
**Candidatos Encontrados ($N=3$):** [50, 65]

| Candidato | Repo | Ruta | Consulta | URL |
| :--- | :--- | :--- | :--- | :--- |
| $B_1$ | `psf/requests` | `src/requests/utils.py` | Consulta 1 | `https://raw.githubusercontent.com/psf/requests/main/src/requests/utils.py` |
| $B_2$ | `pandas-dev/pandas` | `pandas/core/common.py` | Consulta 1 | `https://raw.githubusercontent.com/pandas-dev/pandas/main/pandas/core/common.py` |
| $B_3$ | `numpy/numpy` | `numpy/core/numeric.py` | Consulta 1 | `https://raw.githubusercontent.com/numpy/numpy/main/numpy/core/numeric.py` |

*Nota:* Si la Etapa 3 hubiera devuelto 0 candidatos, el pipeline se detendría e informaría: `[Stage 3 Error]: GitHub Search API returned 0 candidates for the query` [51, 66].

---

#### Etapa 4 — Coincidencia Estructural Basada en AST

##### 4.1. Parseo de AST del Archivo Completo
Los scripts en bruto $B_1, B_2, \dots, B_N$ se recuperan mediante la API de contenidos de GitHub (`/repos/{owner}/{repo}/contents/{path}`) y se parsean en ASTs completos enraizados en nodos `module` o `translation_unit` [51, 66, 68].

##### 4.2. Aislamiento Inicial de Subárboles (Criterios A, B y C)
Para evitar evaluar subárboles sin sentido (como variables individuales o asignaciones primitivas), se filtran los subárboles del AST aplicando tres criterios iniciales **antes** de realizar cualquier aplanamiento de secuencia o puntuación estructural [53, 68]:

* **A. Filtro de Límite de Construcción (Categoría/"Sort" Objetivo):**
  * *Criterio:* La raíz del subárbol candidato debe coincidir con la categoría sintáctica ("sort") del snippet de consulta $a$ [54, 68].
  * *Ejecución:* Si el snippet $a$ es una función independiente, el parser explora cada $B_i$ buscando nodos de nivel superior como `function_definition` o `method_declaration` [54, 68]. Las expresiones anidadas o a nivel de línea se descartan [54, 68].
* **B. Intersección de Nodos de Tag/Ancla (Poda de Funciones No Relacionadas):**
  * *Criterio:* El subárbol debe contener nodos hoja terminales que coincidan con las llamadas a API, funciones o estructuras de datos clave identificadas en la Etapa 2 [55, 68].
  * *Ejecución:* Si la Etapa 2 identificó `sorted`, `items` y `lambda` como anclas funcionales, cualquier subárbol que carezca de estos identificadores terminales se poda de inmediato [55, 68].
* **C. Completitud de Aridad y Alcance:**
  * *Criterio:* El subárbol debe formar un nodo de AST matemáticamente válido y autocontenido bajo las aridades del lenguaje formal [55, 68].
  * *Ejecución:* Garantiza que el subárbol contenga estructuras completas de operador-argumento $o(a_1; \dots; a_n)$, incluyendo parámetros, bloque de sentencias y retornos [55, 68].

*Rendimiento del Pool:* Cada script $B_i$ produce $k_i$ subárboles aislados válidos $b_i$, generando un pool total de $\sum_{i=1}^N k_i$ snippets candidatos para las siguientes fases [70].

##### 4.3. Mapeo de Secuencia de AST ($\mathcal{F}$)
Una vez aislados los subárboles candidatos $b_i$, cada subárbol se aplana individualmente en una secuencia mediante la función de mapeo uno a uno de UniXcoder $\mathcal{F}$ [52, 57, 67, 70, 87]:

$$\mathcal{F}(\text{root}) \to \langle \text{node}, \text{left} \rangle \dots \langle \text{node}, \text{right} \rangle$$

* Los nodos internos/no terminales agregan marcadores direccionales: `<node_name, left>` al entrar y `<node_name, right>` al salir [57, 70, 87].
* Los nodos hoja emiten directamente sus nombres terminales [57, 70, 87].
* *Ejemplo:* Una lista de parámetros se aplana como `<parameters, left> ( data ) <parameters, right>` [57, 70, 87].

##### 4.4. Puntuación de Similitud Estructural y Selección Top-$k$
La secuencia aplanada $\mathcal{F}(b_i)$ se compara contra la secuencia mapeada del snippet de consulta $\mathcal{F}(a)$ usando alineación por árbol de sufijos o distancia de edición de árbol [52, 57, 70]:

* **Candidato $b_1$ (de $B_1$):** El AST coincide con la estructura completa. **Puntaje Estructural AST: 0.94** [52].
* **Candidato $b_2$ (de $B_2$):** Usa `operator.itemgetter(1)` en lugar de `lambda`. **Puntaje Estructural AST: 0.88** [52].
* **Candidato $b_3$ (de $B_3$):** La estructura llama a `np.argsort`. **Puntaje Estructural AST: 0.32** [52].

*Selección Top-$k$ ($k=2$):* Los subárboles candidatos que superan el umbral de similitud estructural ($> 0.70$) avanzan a la Etapa 5 para la verificación semántica basada en vectores [53, 70]. El usuario puede personalizar este umbral según sus requerimientos [70].

##### Diagrama de Flujo de Aislamiento y Puntuación de Subárboles

```
Script Candidato Completo (B_i)
         │
         ▼ [Parseo con Tree-sitter]
AST del Archivo Completo
         │
         ▼ [Criterio A: Filtrar por Tipo de Nodo (p. ej., function_definition)]
Subárboles de Función de Nivel Superior
         │
         ▼ [Criterios B y C: Verificar Anclas de Tags y Completitud de Aridad]
Subárboles Candidatos Aislados (b_i)
         │
         ▼ [Aplicar Función de Mapeo F de UniXcoder a cada b_i]
Secuencias Estructurales Aplanadas F(b_i)
         │
         ▼ [Puntuación por Secuencia de AST / Distancia de Edición de Árbol]
Top-k Candidatos Estructurales Seleccionados
```

---

#### Etapa 5 — Verificación Semántica (Pipeline de UniXcoder)

**Configuración de Codificación:** [58, 71]
* **Modelo:** UniXcoder-base (12 capas Transformer, $d = 768$ estados ocultos, vocabulario de subpalabras BPE de 50,000) [58, 71, 136].
* **Adaptador de Prefijo:** Se antepone el token `[Enc]` para habilitar el modo codificador bidireccional [58, 71, 90].
* **Representación:** Código fuente en bruto (los tokens de AST no terminales se descartan durante la inferencia para maximizar la eficiencia de tokens) [58, 71, 99].

**Capa de Mean Pooling:**
Los estados ocultos $H^N$ de la 12ª capa Transformer se pasan por una capa de mean pooling para extraer vectores normalizados de 768 dimensiones $\mathbf{v}_a, \mathbf{v}_{b_1}, \mathbf{v}_{b_2} \in \mathbb{R}^{768}$ [58, 71, 96].

**Cálculo de Similitud Coseno:** [59, 72]
$$\text{Sim}_{\text{semantic}}(a, b_i) = \cos(\mathbf{v}_a, \mathbf{v}_{b_i}) = \frac{\mathbf{v}_a \cdot \mathbf{v}_{b_i}}{\|\mathbf{v}_a\|_2 \|\mathbf{v}_{b_i}\|_2}$$

**Puntuaciones de Verificación Semántica:** [59, 72]
* **Candidato $b_1$:** Similitud Coseno = **0.962** (Identidad semántica alta; coincidencia exacta de la lógica de ordenamiento y extracción de la clave lambda) [59, 72].
* **Candidato $b_2$:** Similitud Coseno = **0.915** (Identidad semántica alta; UniXcoder reconoce que `operator.itemgetter(1)` es funcionalmente idéntico a `lambda item: item[1]` a pesar de las diferencias estructurales en el AST) [59, 72].

---

#### Salida Final — Candidatos Top-$k$ Verificados y Ordenados

| Rango | Repositorio de Origen y Ruta de Archivo | Snippet de Código Coincidente | Similitud AST | Puntuación Semántica UniXcoder | Consulta de Búsqueda en GitHub |
| :---: | :--- | :--- | :---: | :---: | :--- |
| **1** | `psf/requests`<br>`src/requests/utils.py` | ```python\ndef revrank_dict(d, reverse=True):\n    return dict(sorted(d.items(), key=lambda t: t[1], reverse=reverse))\n``` | 0.94 | **0.962** | `python dict sort key lambda items` |
| **2** | `pandas-dev/pandas`<br>`pandas/core/common.py` | ```python\ndef sort_dict_by_val(d):\n    return dict(sorted(d.items(), key=operator.itemgetter(1)))\n``` | 0.88 | **0.915** | `python dict sort key lambda items` |

---

#### Conclusión y Alcance
Esta solución aplica al caso donde el lenguaje del snippet $a$ coincide con el lenguaje del pool de candidatos $B$ [61, 74]. En versiones avanzadas se podrían considerar mapeos cruzados de tags entre lenguajes mediante funciones de transformación $f: \text{Tags}(L_a) \to \text{Tags}(L_b)$, complementado con la capacidad nativa de UniXcoder para búsqueda *zero-shot* entre lenguajes distintos [61, 74, 99, 112].
