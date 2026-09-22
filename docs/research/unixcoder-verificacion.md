# Documento de Decisión: Verificación Semántica con UniXcoder, Cotas de Escalamiento y Contrato de Salida

**Versión del Documento:** 1.0  
**Estado:** Registro de Decisión Arquitectónica  
**Objetivo:** Pipeline de Búsqueda de Semantica de Código (Etapa 5: Verificación Semántica),   

---

## 1. Resumen Ejecutivo

Este documento de decisión establece la arquitectura técnica, el contrato operacional, las cotas de complejidad matemática, la evaluación empírica de rendimiento y la viabilidad económica de la **Etapa 5: Verificación Semántica** dentro del Pipeline de Búsqueda y Verificación de Clones de Código.

Para lograr una verificación de clones de código semántica de alta precisión manteniendo latencias operativas predecibles, adoptamos **UniXcoder-base** (`microsoft/unixcoder-base`) ejecutado localmente en modo `**<encoder-only>` con mean pooling** y **normalización vectorial L2**. La similitud semántica entre los snippets objetivo y los subárboles candidatos AST se mide mediante la similitud coseno de vectores en $\mathbb{R}^{768}$.

### Resumen de Decisiones Clave y Actualizaciones de la Versión 5.1:

1. **Integración Empírica del Reporte de Ejecución (`execution_report.md`):**
  - **Ventana de Contexto **$L = 1023$** tokens:** El incremento de la longitud máxima de tokenización de $512$ a $1023$ tokens incrementó la similitud semántica de $0.7940$ a $0.9003$ en código completo, confirmando que incluir *imports*, firmas de función y lógica de post-procesamiento es crítico para capturar la intención funcional completa.
  - **Comportamiento ante Truncamiento Silencioso:** Scripts que superan el límite de $1023$ tokens (ej. $12{,}000+$ tokens) no generan excepciones en PyTorch, pero son **truncados internamente a **$1019$** tokens** (`max_length - 4`), descartando el código excedente sin advertencias.
  - **Perfil de Recursos Operacionales:** La inferencia en CPU sobre secuencias de $1024$ tokens requiere un tiempo de $\sim 0.44\text{--}0.47\text{ s}$ por par debido a la atención fija. Consume $\sim 925\text{ MB}$ de RAM física (gestionada en tensores C++ de PyTorch), $0\%$ swap, $7$ hilos de ejecución activos y un uso de memoria Python nativo ínfimo ($\sim 137\text{--}199\text{ KB}$).
2. **Cotas Estimativas de Candidatos (**$N$** y** $k_i$**):**
  - **Scripts Candidatos (**$N$**):** La API de búsqueda de GitHub (Etapa 3) recupera un pool inicial de $N \approx 100 \text{ a } 500$ archivos candidatos por consulta.
  - **Snippets Candidatos por Script (**$k_i$**):** El parseo de AST (Etapa 4) extrae $k_i \approx 1 \text{ a } 5$ subárboles de función por script (promedio $\bar{k}_i \approx 2$).
  - **Filtrado Estructural AST (**$N \to K$**):** El pool total sin filtrado $K_{\text{bruto}} = \sum_{i=1}^N k_i \approx 200 \text{ a } 1{,}500$ subárboles se reduce mediante los criterios de anclas AST y aridad a un techo controlado de $K_{\text{filtrado}} \le 30 \text{ a } 50$ **snippets**.
3. **Reducción de la Complejidad Temporal a **$\mathcal{O}(K)$**:**
  - Considerando que el número de capas Transformer ($n_{\text{layers}} = 12$), la dimensión del espacio latente ($d = 768$) y la longitud máxima de secuencia ($L \le 1023$) son parámetros constantes fijos del modelo y del entorno, toda la expresión de complejidad temporal para la generación de embeddings y comparación de similitud coseno se reduce estrictamente a:
  
     $$\mathcal{O}(K)$$
  
     demostrando que el tiempo de cómputo escala linealmente con respecto al número de snippets candidatos $K$.
4. **Requerimiento Crítico de Persistencia del Modelo (Arranque en Caliente):**
  - **Problema:** La re-instanciación del modelo Transformer desde el caché de Hugging Face en cada ejecución del script añade una sobrecarga inaceptable de $\sim 1.1 \text{ a } 1.5 \text{ segundos}$ de arranque en frío.
  - **Solución Arquitectónica:** Se mandata el despliegue de UniXcoder mediante un **servidor de inferencia persistente en memoria** (FastAPI / gRPC / demonio Worker en segundo plano), manteniendo los pesos en RAM/VRAM para reducir la latencia de carga a $0\text{ ms}$ en consultas *online*.

---

## 2. Configuración Local y Arquitectura de Inferencia

### 2.1 Especificación del Modelo y Pesos

- **Arquitectura Base:** Transformer de 12 capas ($n_{\text{layers}} = 12$), $d = 768$ dimensiones ocultas, 12 cabezales de atención ($h = 12$, $d_k = 64$), vocabulario BPE de 50,000 subpalabras + 1,416 tokens especiales para nodos AST.
- **Identificador de Modelo:** `microsoft/unixcoder-base` (~125 Millones de parámetros, ~500 MB en disco).
- **Entorno de Inferencia:** PyTorch 2.x en modo offline/air-gapped (`torch.device("cuda")` si hay GPU disponible, o `torch.device("cpu")`).

### 2.2 Tokenización y Selección de Modo

UniXcoder controla su comportamiento mediante tokens de prefijo especiales y máscaras de atención específicas:

$$
\text{tokens} = [\text{CLS}, \text{Enc}, \text{SEP}] + \text{tokenize}(\text{code})[:\text{max\_length}-4] + [\text{SEP}]
$$

- **Prefijo:** `"<encoder-only>"` (`[Enc]`).
- **Máscara de Atención:** Matriz totalmente en ceros $M_{ij} = 0$, permitiendo atención bidireccional entre todos los tokens.
- **Límite de Longitud de Secuencia (**$\text{max\_length}$**):**
  - **Modo Estándar:** $\text{max\_length} = 512$ tokens ($508$ tokens de código efectivo).
  - **Modo Contexto Extendido:** $\text{max\_length} = 1023$ tokens ($1019$ tokens de código efectivo).
  - **Límite Arquitectónico Máximo:** $1023$ tokens. Ajustar $\text{max\_length} \ge 1024$ dispara una excepción `AssertionError` en `unixcoder.py`.

### 2.3 Extracción de Características: Mean Pooling y Normalización L2

Para una secuencia de tokens de entrada $X = (x_1, \dots, x_L)$ con máscara de tokens válidos $m \in \{0, 1\}^L$, UniXcoder genera los estados ocultos de la 12ª capa Transformer $H^{12} \in \mathbb{R}^{L \times 768}$:

1. **Capa de Mean Pooling:**
  $$
  \mathbf{v}_{\text{raw}} = \frac{\sum_{i=1}^L (H_i^{12} \cdot m_i)}{\sum_{i=1}^L m_i} \in \mathbb{R}^{768}
  $$
2. **Normalización Unitaria L2:**
  $$
  \mathbf{v} = \frac{\mathbf{v}_{\text{raw}}}{\|\mathbf{v}_{\text{raw}}\|_2} \in \mathbb{R}^{768}, \quad \|\mathbf{v}\|_2 = 1.0
  $$
3. **Cálculo de Similitud Coseno:**
  $$
  \text{Sim}_{\text{semantica}}(a, b_i) = \cos(\mathbf{v}_a, \mathbf{v}_{b_i}) = \mathbf{v}_a \cdot \mathbf{v}_{b_i}^T \in [-1.0, 1.0]
  $$

---

## 3. Resultados Empíricos del Reporte de Ejecución (`execution_report.md`)

Los experimentos con la herramienta de pruebas (`execution_report.md`) analizando scripts en Python de conteo de frecuencia de palabras (`word_freq_A.py` de 545 tokens y `word_freq_B.py` de 610 tokens) revelan las siguientes características del modelo:

### 3.1 Impacto de la Longitud de Contexto ($512$ vs. $1023$ Tokens)


| Configuración de Longitud ($\text{max\_length}$) | Tokens de Código Procesados | Similitud Coseno Obtenida | Tiempo de Inferencia CPU | Interpretación del Resultado                                                       |
| :------------------------------------------------: | :---------------------------: | :-------------------------: | :------------------------: | :---------------------------------------------------------------------------------- |
| $\text{max\_length} = 512$                       | $508$ tokens                | $0.7940$                  | $\sim 0.18\text{ s}$     | Representación parcial. Trunca definiciones secundarias e *imports*.               |
| $\text{max\_length} = 1023$                      | $1019$ tokens               | $0.9003$                  | $\sim 0.45\text{ s}$     | **Contexto completo.** Incluye módulos, funciones auxiliares y post-procesamiento. |


- **Conclusión de Contexto:** Configurar $\text{max\_length} = 1023$ incrementa la precisión semántica en $+10.63$ puntos porcentuales ($0.7940 \to 0.9003$), confirmando que capturar el contexto completo del archivo es esencial cuando el snippet cabe dentro de la ventana del Transformer.

### 3.2 Comportamiento ante Scripts Largos ($> 1023$ Tokens)

1. **Truncamiento Silencioso:** Cuando un archivo supera los $1023$ tokens (probado con scripts de $3{,}000 \text{ a } 12{,}000+$ tokens), el método `tokenize()` realiza un corte interno a los primeros $1019$ tokens. El código excedente es ignorado sin lanzar *warnings* ni excepciones.
2. **Estabilidad de Similitud:** En scripts excesivamente largos, la similitud se estabiliza alrededor de $0.9189$, reflejando la coincidencia de los bloques iniciales del archivo.
3. **Tiempo de Cómputo Constante:** El tiempo de inferencia se mantiene rígido en $\sim 0.44 \text{--} 0.47\text{ s}$ independientemente de si el archivo tiene $1{,}200$ u $11{,}000$ tokens, ya que la matriz de atención cuadrática en el Transformer siempre opera sobre el tamaño de secuencia fijo padding/truncated a $1024$.

### 3.3 Medición de Recursos del Sistema

- **Memoria RAM Física:** La presión de memoria total del proceso Python + PyTorch se estabiliza en $\sim 925\text{ MB}$, alojada en tensores C++ no administrados por el recolector de basura de Python.
- **Memoria Swap / Paginación:** $0\text{ MB}$ **de uso de swap**, operando enteramente dentro de la RAM.
- **Uso de Hilos:** $7$ hilos de ejecución concurrentes (intérprete de Python + trabajadores OpenMP de PyTorch).
- **Sobrecarga de Carga del Modelo en Frío:** La primera instanciación del modelo descargando/leyendo desde el caché local de Hugging Face toma $\sim 1.1\text{ a } 1.5\text{ segundos}$ **adicionales**.

---

## 4. Cotas Estimativas de Candidatos ($N$ y $k_i$) y Reducción de Complejidad Temporal

### 4.1 Definición de Variables del Pipeline

El flujo de recuperación y verificación opera bajo las siguientes variables cuantitativas:

- $N$ **(Scripts Candidatos):** Cantidad de archivos de código fuente recuperados en la Etapa 3 desde la API de Búsqueda de GitHub (`GET /search/code`).
  $$
  \text{Cota Estimativa de Scripts Candidatos: } N \in [100, 500] \text{ archivos por consulta}
  $$
- $k_i$ **(Snippets Candidatos por Script **$B_i$**):** Cantidad de subárboles de función aislados dentro del archivo candidato $B_i$ durante la Etapa 4 mediante Tree-sitter.
  $$
  \text{Cota Estimativa por Archivo: } k_i \in [1, 5] \text{ subárboles de función} \quad (\text{Promedio: } \bar{k}_i \approx 2)
  $$
- $K_{\text{bruto}}$ **(Snippets Totales sin Filtrado):**
  $$
  K_{\text{bruto}} = \sum_{i=1}^N k_i = N \cdot \bar{k}_i \implies K_{\text{bruto}} \in [200, 1500] \text{ subárboles}
  $$
- $K_{\text{filtrado}}$ **(Snippets Elegibles para Etapa 5):** Aplicando los tres criterios de selección de la Etapa 4 (*Filtro de Límite de Construcción*, *Intersección de Nodos Ancla* y *Completitud de Aridad*):
Se fija un techo recomendado de candidatos $K_{\text{max}}$:
  $$
  K_{\text{filtrado}} \le K_{\text{max}} = 30 \text{ a } 50 \text{ subárboles}
  $$

### 4.2 Reducción de Complejidad Temporal a $\mathcal{O}(K)$

En la Etapa 5, el cómputo de la verificación semántica comprende la codificación en el Transformer y el cálculo de la similitud coseno. La formulación matemática detallada por secuencia viene dada por:

$$
\begin{aligned}
\text{Complejidad}_{\text{Transformer}} &= (1 + K) \cdot n_{\text{layers}} \cdot \left( 12 \cdot L \cdot d^2 + 2 \cdot L^2 \cdot d \right) \\
\text{Complejidad}_{\text{Comparacion}} &= K \cdot d
\end{aligned}
$$

Al analizar las variables del sistema bajo condiciones operativas:

1. El número de capas del modelo es constante: $n_{\text{layers}} = 12$.
2. La dimensión oculta del espacio vectorial es constante: $d = 768$.
3. La longitud máxima de tokens está acotada por la ventana de tokenización: $L \le 1023$ (o $L \le 512$), actuando como constante superior.

Al despreciar todas las constantes de la arquitectura del modelo ($n_{\text{layers}}$, $d$ y $L$), la expresión de complejidad temporal global para la generación de embeddings y comparación vectorial se reduce a:

$$
\mathcal{O}(K)
$$

Donde $K$ es la cantidad de snippets candidatos que ingresan a la Etapa 5. Esta reducción lineal directa confirma que el filtrado estructural AST de la Etapa 4 (que reduce $K_{\text{bruto}} \approx 1500 \to K_{\text{filtrado}} \le 50$) es el factor crítico para garantizar tiempos de respuesta en tiempo real.

### 4.3 Tabla Comparativa de Escalamiento del Tiempo de Cómputo

A continuación se muestra cómo escala el tiempo de procesamiento según el volumen de candidatos y el estado de optimización del sistema:


| Escenario de Inferencia                              | Archivos ($N$) | Snippets ($K$) | Longitud ($L$) | Carga Modelo ($T_{\text{carga}}$) | Tiempo Embedding CPU                    | Tiempo Inferencia GPU | Tiempo Total Estimado | Estado de Viabilidad                           |
| :---------------------------------------------------- | :--------------: | :--------------: | :--------------: | :---------------------------------: | :---------------------------------------: | :---------------------: | :---------------------: | :---------------------------------------------- |
| **Sin Filtrado AST + Sin Persistencia (Worst Case)** | $500$          | $1{,}500$      | $1023$         | $1{,}100\text{ ms}$               | $\sim 675\text{ s}$ ($11.2\text{ min}$) | $\sim 6.75\text{ s}$  | $\sim 676.1\text{ s}$ | ❌ **PROHIBITIVO** (Timeout en CPU)             |
| **Sin Filtrado AST + Con Persistencia**              | $500$          | $1{,}500$      | $512$          | $0\text{ ms}$                     | $\sim 27.7\text{ s}$                    | $\sim 0.60\text{ s}$  | $\sim 27.7\text{ s}$  | ⚠️ **LENTO** (Supera SLA de API)               |
| **Con Filtrado AST + Sin Persistencia**              | $500$          | $30$           | $512$          | $1{,}100\text{ ms}$               | $\sim 0.55\text{ s}$                    | $\sim 0.012\text{ s}$ | $\sim 1.65\text{ s}$  | ⚠️ **REGULAR** (Lassitud por arranque en frío) |
| **Filtrado AST + Servicio Persistente CPU**          | $500$          | $30$           | $512$          | $0\text{ ms}$                     | $\sim 0.55\text{ s}$                    | N/A                   | $\sim 0.55\text{ s}$  | 🟡 **ACEPTABLE** (SLA real-time borde)         |
| **Filtrado AST + Servicio Persistente GPU (Óptimo)** | $500$          | $30$           | $512$          | $0\text{ ms}$                     | N/A                                     | $\sim 0.012\text{ s}$ | $\sim 12.5\text{ ms}$ | 🚀 **PRODUCCIÓN ÓPTIMA** ($< 15\text{ ms}$)    |


---

## 5. Requerimiento Arquitectónico: Persistencia del Modelo en Memoria

### 5.1 Diagnóstico del Cuello de Botella de Carga

Actualmente, ejecutar scripts en modo CLI invocando `UniXcoder("microsoft/unixcoder-base")` obliga al intérprete de Python a:

1. Buscar y leer las carpetas del caché de Hugging Face en disco (`/home/sandbox/.cache/huggingface/...`).
2. Re-asignar $\sim 500\text{ MB}$ de tensores PyTorch en la memoria RAM/VRAM.
3. Re-instanciar la estructura de 12 capas Transformer en C++.

Este proceso introduce una latencia fija no computable de $1{,}100 \text{ a } 1{,}500\text{ ms}$ **por cada consulta**, dominando el $90\%$ del tiempo de respuesta en ejecuciones filtradas.

### 5.2 Solución Requerida: Servicio de Inferencia "Warm-Start"

Para eliminar este cuello de botella, el sistema debe implementar una arquitectura de modelo persistente en memoria:

```
[Cliente Búsqueda API / UI] 
          │
          ▼ (Consulta gRPC / HTTP REST JSON)
┌─────────────────────────────────────────────────────────┐
│ Servidor de Inferencia Persistente (FastAPI / gRPC)     │
│  ┌───────────────────────────────────────────────────┐  │
│  │ Modelo UniXcoder en Memoria RAM / VRAM Caliente   │  │
│  │ (Instanciado 1 sola vez al iniciar el contenedor) │  │
│  └───────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

### 5.3 Opciones de Implementación Recomendadas:

1. **Microservicio gRPC / FastAPI con Worker Residente:**
 Cargar el modelo durante el evento de inicio del servidor (`lifespan` / `@app.on_event("startup")`). El endpoint recibe los snippets en texto y retorna directamente la matriz de vectores de $768$ dimensiones.
2. **Motor de Inferencia ONNX Runtime:**
 Exportar UniXcoder a formato `.onnx` (`sailesh27/unixcoder-base-onnx`) utilizando ejecución multilenguaje en C++/Node.js/Python, reduciendo el consumo de memoria a $\sim 300\text{ MB}$ y tiempo de carga inicial a $< 200\text{ ms}$.
3. **Servidor Triton Inference Server / TorchServe:**
 Para despliegues a gran escala con escalado dinámico de lotes (*dynamic batching*) y balanceo entre GPU y CPU.

---

## 8. Conclusiones y Decisiones Finales

1. **Adopción de Entrada en Código Bruto:** La Etapa 5 procesa únicamente código fuente en bruto. Los tags de LLM del Issue #7 se utilizan exclusivamente en las Etapas 2 y 3 para la construcción de consultas a la API de GitHub.
2. **Uso de ventana **$\text{max\_length} = 1023$**:** Se aprueba el uso del límite de $1023$ tokens para snippets de contexto completo. Se debe agregar una alerta en los *logs* cuando un snippet supere los $1019$ tokens para notificar al usuario sobre el truncamiento silencioso.
3. **Aislamiento AST Requerido:** Se ratifica que la Etapa 4 debe filtrar los $N \approx 500$ archivos recuperados a un techo $K \le 50$ subárboles candidatos antes de invocar la Etapa 5.
4. **Reducción de Complejidad a **$\mathcal{O}(K)$**:** Se formaliza que al tratar los parámetros de la arquitectura como constantes ($n_{\text{layers}}=12, d=768, L\le 1023$), la complejidad del proceso de embedding escala estrictamente como $\mathcal{O}(K)$.
5. **Mandato de Persistencia del Modelo:** Se establece como requisito de infraestructura implementar un servidor persistente (FastAPI/gRPC/ONNX) para mantener los pesos de UniXcoder cargados en memoria, eliminando el costo de $1.1\text{ s}$ de arranque en frío por consulta.

