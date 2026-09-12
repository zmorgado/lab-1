# Paso 4 (Criterios Iniciales de Selección de Subárboles): Reducción Válida del Espacio de Búsqueda

El Paso 4 (Criterios Iniciales de Selección de Subárboles) proporciona una reducción del pool de candidatos matemática y estructuralmente válida, ya que actúa como un tamiz sintáctico determinista.

Cuando la búsqueda de código de la API de GitHub recupera scripts candidatos completos ($B_i$), cada script produce un AST masivo enraizado en un nodo `module` o `translation_unit` de nivel superior. Intentar calcular alineaciones de árboles estructurales o embeddings vectoriales de 768 dimensiones de UniXcoder sobre cada nodo arbitrario o archivo de miles de líneas es computacionalmente prohibitivo y ruidoso.

El Paso 4 valida y reduce este espacio de candidatos a un pool acotado de $k$ subárboles aislados ($b_i$) por archivo, mediante tres garantías de filtrado específicas:

## 1. Alineación Gramatical y de Categoría (Criterio A: Filtro de Límite de Construcción)

- **Por qué es válido:** Un snippet de consulta $a$ que representa una función independiente no puede ser semánticamente equivalente a una asignación de una sola línea o a una expresión binaria dentro del archivo candidato $B_i$.
- **Efecto de reducción:** Al buscar específicamente nodos raíz que coincidan con la categoría sintáctica ("sort") del snippet objetivo $a$ (como `function_definition` o `method_declaration`), el parser filtra millones de subárboles de AST irrelevantes a nivel de línea o de expresión, sin perder funciones candidatas.

## 2. Intersección de Anclas Léxicas y Funcionales (Criterio B: Filtro de Tag/Ancla)

- **Por qué es válido:** La extracción de tags de la Etapa 2 identifica las llamadas a API, funciones de librería y símbolos hoja terminales esenciales (como `sorted()`, `dict.items()` o `lambda`) requeridos para el algoritmo específico. Los nodos hoja en un AST representan símbolos terminales concretos.
- **Efecto de reducción:** Cualquier subárbol de función candidata en $B_i$ que carezca por completo de estos identificadores hoja terminales se poda de inmediato. Esto elimina funciones estructuralmente similares pero semánticamente no relacionadas antes de ejecutar alineaciones costosas por distancia de edición de AST o pasadas por el modelo.

## 3. Completitud Formal de Alcance y Aridad (Criterio C: Completitud de Aridad)

- **Por qué es válido:** Bajo las definiciones formales de AST, las construcciones del lenguaje se forman mediante operadores que combinan subárboles de argumentos $o(a_1; \dots; a_n)$. Un snippet no puede someterse a una verificación semántica precisa si su fragmento de AST está truncado o le faltan bloques de parámetros, cuerpos o valores de retorno.
- **Efecto de reducción:** Garantiza que cada subárbol aislado en el pool de candidatos forme una unidad matemáticamente completa y autocontenida, capaz de una evaluación completa en la Etapa 5.

## Resumen de la Eficiencia del Pipeline

```
Archivos Candidatos Completos (B_i)   [N archivos, ASTs grandes a nivel de módulo]
         │
         ▼  Filtrado del Paso 4
         (Criterios A, B y C)
Pool de Subárboles Candidatos (b_i)   [n · k subárboles de función aislados y bien formados]
         │
         ▼  Alineación Estructural de la Etapa 4.1 y Umbral Top-k (> 0.70)
Pool de Candidatos Filtrado            [Los candidatos Top-k avanzan]
         │
         ▼  Verificación Semántica UniXcoder de la Etapa 5 (Similitud Coseno en R^768)
Clones Finales Verificados
```

Al filtrar fragmentos incompletos, desajustes de categoría y subárboles carentes de anclas a nivel de AST, el Paso 4 garantiza que el 100% de los subárboles candidatos que ingresan a la puntuación estructural y a la verificación vectorial de UniXcoder sean implementaciones estructuralmente plausibles y autocontenidas.
