# Pipeline de Recuperación y Comparacion de Codigo
 
Ejecución paso a paso del pipeline de recuperación y comparacion de código, manteniendo trazabilidad, criterios de coincidencia explícitos en cada etapa, y verificación semántica basada en UniXcoder.
 
## Marco de Ejecución del Pipeline y Definiciones de Coincidencia
 
Para evitar confundir la estructura sintáctica con la semántica de ejecución, cada etapa aplica un criterio de coincidencia distinto:
 
- **Coincidencia Léxica (Etapa 3):** Coocurrencia de palabras clave y símbolos dentro del texto fuente, identificadores y metadatos del repositorio, indexados por la API de GitHub. Proporciona un recall grueso de candidatos, pero no evalúa similitud estructural ni funcional. Agregar instancia interactiva con el usuario para agregar tags que el programa no logre considerar significativos.
- **Coincidencia Estructural (Etapa 4):** Congruencia en la geometría del árbol de sintaxis, tipos de nodo del AST (p. ej., `function_definition`, `call`, `lambda`) y relaciones padre-hijo. La similitud de AST garantiza una organización sintáctica similar, pero no implica una ejecución semántica idéntica. Esta etapa garantiza snippets verosimiles en tanto a lingitud, como conceptualmente autocontenidos, pero a su vez representa la instancia de mayor riesgo de omicion de canditato optimo... Evaluar posible agencia del usuario en el proceso de seleccion; puntaje minimo de coincidencia etc...
- **Coincidencia Semántica (Etapa 5):** Equivalencia funcional y conceptual de alto nivel entre fragmentos de código, medida mediante similitud coseno de vectores en el espacio latente continuo de 768 dimensiones de UniXcoder (ℝ⁷⁶⁸). Dos fragmentos de código pueden ser una coincidencia semántica total incluso sin superposición léxica superficial o con árboles de sintaxis estructuralmente distintos. Resultados verosimiles, computo costoso.
---
 
## Etapa 1 — Extracción del Snippet
 
**Script Fuente A:** *Ej* `local_repository/utils/dictionary_helpers.py`
 
**Método de Extracción:** Mediante un parser de AST (p. ej., Tree-sitter o el módulo `ast` nativo de Python), el script A se analiza para localizar construcciones estructurales de nivel superior. El snippet objetivo `a` se aísla usando los límites de desplazamiento de bytes de su nodo (`start_byte` a `end_byte`).
 
**Snippet Objetivo Extraído a:**
 
```python
def rank_dictionary_by_value(input_dict, reverse_order=True):
    """Sort a Python dictionary by its values and return a new dictionary."""
    sorted_pairs = sorted(input_dict.items(), key=lambda item: item[1], reverse=reverse_order)
    return dict(sorted_pairs)
```
 
---
 
## Etapa 2 — Extracción de Tags
 
Al analizar el snippet `a` se obtienen sus descriptores conceptuales y funcionales centrales:
 
- **Nombre del Algoritmo:** Ordenamiento de diccionario / Ranking por valor
- **Estructura de Datos:** `dict` (mapa hash), lista de tuplas clave-valor
- **Patrón de Diseño / Paradigma:** Mapeo de función clave de orden superior (`lambda`)
- **Llamadas a Librería / API:** `sorted()`, `dict.items()`, `dict()`
- **Palabras Clave de Dominio:** Python, ranking por valor, ordenar diccionario
**Consultas de Búsqueda Ordenadas para la API de GitHub (`/search/code`):**
- **Tags agregados del usuario**
 
1. `python dict sort key lambda items`
2. `sorted dict.items key lambda value`
3. `def rank dict sorted language:python`
---
 
## Etapa 3 — Búsqueda en GitHub (Recuperación Léxica de Candidatos)
 
**Ejecución de API:** `GET https://api.github.com/search/code?q=python+dict+sort+key+lambda+items+language:python`
 
**Candidatos Encontrados (N=3):**
 
| Candidato | Repo | Ruta | Consulta | URL |
|---|---|---|---|---|
| B₁ | psf/requests | `src/requests/utils.py` | Consulta 1 | `https://raw.githubusercontent.com/psf/requests/main/src/requests/utils.py` |
| B₂ | pandas-dev/pandas | `pandas/core/common.py` | Consulta 1 | `https://raw.githubusercontent.com/pandas-dev/pandas/main/pandas/core/common.py` |
| B₃ | numpy/numpy | `numpy/core/numeric.py` | Consulta 1 | `https://raw.githubusercontent.com/numpy/numpy/main/numpy/core/numeric.py` |
 
> **Nota:** Si la Etapa 3 hubiera devuelto 0 candidatos, el pipeline se detendría aquí e informaría:
> `[Stage 3 Error]: GitHub Search API returned 0 candidates for the query.`
 
---
 
## Etapa 4 — Coincidencia Estructural Basada en AST
 
**Parseo de AST:** Los scripts en bruto B₁, B₂, B₃ se recuperan mediante la API de contenidos de GitHub (`/repos/{owner}/{repo}/contents/{path}`) y se parsean en AST.
 
**Aislamiento de Subárboles:** Tree-sitter aísla los subárboles `function_definition` dentro de cada candidato.
 
**Mapeo de Secuencia de AST (𝓕):** Los subárboles se aplanan usando la función de mapeo uno a uno de UniXcoder, 𝓕:
 
```
𝓕(root) → ⟨node, left⟩ … ⟨node, right⟩
```
 
Esto conserva la jerarquía estructural mientras convierte los nodos en tokens de secuencia.
 
### Criterios Iniciales de Selección de Subárboles
 
Para aislar subárboles candidatos a partir de un archivo candidato recuperado (Bᵢ), el pipeline aplica tres criterios de selección iniciales que filtran el árbol de sintaxis antes de ejecutar la puntuación estructural.
 
Cuando un script candidato Bᵢ se parsea en un AST (p. ej., con Tree-sitter), el archivo produce un árbol grande enraizado en un nodo `module` o `translation_unit`. Para evitar evaluar subárboles sin sentido (como variables individuales o asignaciones primitivas), los subárboles se filtran usando:
 
**A. Filtro de Límite de Construcción (Categoría/"Sort" Objetivo)**
- **Criterio:** La raíz del subárbol candidato debe coincidir con la categoría sintáctica ("el maso menos a que va") del snippet de consulta `a`.
- **Ejecución:** Si el snippet original `a` es una función independiente, el parser explora cada Bᵢ perteneciente al pool B extraido de GitHub buscando específicamente nodos de construcción de nivel superior, como `function_definition` o `method_declaration`. Las expresiones anidadas o nodos a nivel de línea (como una asignación individual o `binary_operator`) se descartan como candidatos para la comparación independiente.
**B. Intersección de Nodos de Tag/Ancla (Poda de Funciones No Relacionadas)**
- **Criterio:** El subárbol candidato debe contener nodos hoja terminales que coincidan con las llamadas a API, funciones de librería o estructuras de datos clave identificadas en la Etapa 2.
- **Ejecución:** En un AST, los nodos hoja representan símbolos terminales concretos (identificadores, literales, operadores). Si la Etapa 2 identificó `sorted`, `items` y `lambda` como anclas funcionales, cualquier subárbol `function_definition` en Bᵢ que carezca de estos identificadores hoja se poda de inmediato.
**C. Completitud de Aridad y Alcance**
- **Criterio:** El subárbol debe formar un nodo de AST matemáticamente válido y autocontenido bajo las aridades del lenguaje formal.
- **Ejecución:** La selección garantiza que el subárbol contenga estructuras completas de operador-argumento o(a₁; …; aₙ) — incluyendo listas de parámetros, bloques de sentencias del cuerpo y sentencias de retorno.
**Flujo de aislamiento y puntuación de subárboles:**
 
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
         ▼ [Aplicar Función de Mapeo F de UniXcoder]
Secuencias Estructurales Aplanadas F(b_i)
         │
         ▼ [Puntuación por Secuencia de AST / Distancia de Edición de Árbol]
Puntuaciones Estructurales Top-k Más Altas
```
 
1. **Extracción del Subárbol:** El parser aísla el subárbol objetivo T(bᵢ) usando sus rangos exactos de bytes (`start_byte` a `end_byte`) en el caso definido por el limite te tokens definido por UnixCoder.
2. **Aplanado mediante Mapeo Uno a Uno 𝓕:** Para capturar la jerarquía del árbol sin perder información estructural, cada subárbol aislado se mapea a una secuencia de tokens mediante la función de mapeo 𝓕 de UniXcoder:
   - Los nodos internos/no terminales agregan marcadores direccionales: `<node_name, left>` al entrar y `<node_name, right>` al salir.
   - Los nodos hoja emiten directamente sus nombres terminales.
   - Ejemplo: una lista de parámetros se aplana como `<parameters, left> ( data ) <parameters, right>`.
   - **Considereaciones** Este proceso hasta este punto es iterado sobre todo el pool B es decir #B = n cantidad de itereaciones. Sobre cada _Bi_ se generaran Ki cantidad de snippets candidatos. Resultando en una cantidad Kn snippets.
3. **Puntuación de Similitud Estructural:** La secuencia aplanada 𝓕(bᵢ) se compara contra la secuencia mapeada del snippet de consulta 𝓕(a) usando alineación por árbol de sufijos o distancia de edición de árbol.
4. **Selección Top-k:** Los subárboles candidatos con las puntuaciones de similitud estructural más altas avanzan a la Etapa 5 para la verificación semántica basada en vectores en UniXcoder. Aqui el usuario podria setear su propio umbral de tolerancia a su propio riesgo. El que tiene 32 de RAM que haga lo que quiera.
---
 
## Etapa 5 — Verificación Semántica (Pipeline de UniXcoder)
 
**Configuración de Codificación:**
 **El algoritmo ya detallado en el Latex de pipeline (Source Code - Vector Embeding)
- **Modelo:** UniXcoder-base (12 capas Transformer, d = 768 estados ocultos, vocabulario de subpalabras BPE de 50,000)
- **Adaptador de Prefijo:** Se antepone el token de prefijo `[Enc]` para el modo codificador bidireccional
- **Representación:** Código fuente en bruto (los tokens de AST no terminales se descartan durante la inferencia de grano fino para maximizar la eficiencia de tokens)
**Capa de Mean Pooling:** Los estados ocultos Hᴺ de la 12ª capa Transformer se pasan por una capa de mean pooling para extraer vectores normalizados de 768 dimensiones **v**ₐ, **v**_b1, **v**_b2 ∈ ℝ⁷⁶⁸.
 
**Cálculo de Similitud Coseno:**
 
```
Sim_semantic(a, b_i) = cos(v_a, v_bi) = (v_a · v_bi) / (‖v_a‖₂ ‖v_bi‖₂)
```
 
**Puntuaciones de Verificación:**
 
- **Candidato bi:** Similitud Coseno = **0.962** (Identidad semántica alta; coincidencia exacta de la lógica de ordenamiento y extracción de la clave lambda)
- **Candidato bi+1:** Similitud Coseno = **0.915** (Identidad semántica alta; UniXcoder reconoce que `operator.itemgetter(1)` es funcionalmente idéntico a `lambda item: item[1]` a pesar de las diferencias estructurales en el AST)
---
 
## Salida Final — Candidatos Top-k Verificados y Ordenados
 
| Rango | Repositorio de Origen y Ruta de Archivo | Snippet de Código Coincidente | Similitud AST | Puntuación Semántica UniXcoder | Consulta de Búsqueda en GitHub |
|---|---|---|---|---|---|
| 1 | `psf/requests`<br>`src/requests/utils.py` | ```python\ndef revrank_dict(d, reverse=True):\n    return dict(sorted(d.items(), key=lambda t: t[1], reverse=reverse))\n``` | 0.94 | 0.962 | `python dict sort key lambda items` |
| 2 | `pandas-dev/pandas`<br>`pandas/core/common.py` | ```python\ndef sort_dict_by_val(d):\n    return dict(sorted(d.items(), key=operator.itemgetter(1)))\n``` | 0.88 | 0.915 | `python dict sort key lambda items` |
 
---
 
**Conclusion**
Esta solucion pertenece al unico caso en el que el lenguage de snippet a coincida con el lenguage del pool B resultante. Se podrian considerar mapeos inter combencion de tags entre lenguages pero por ahora es mucho y ademas hay tags que definen inefectiblemente el lenguage de busqueda como ponele el metodo de llamado a una API.
 

