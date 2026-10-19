import { Highlight, type PrismTheme } from 'prism-react-renderer'
import type { LineRange } from '@/types/Explanations'

// Las tintas de sintaxis del Om Theme (A Darker Dracula Theme), leidas de los
// tokens: el codigo va sobre el papel de la pagina, asi que el fondo queda
// transparente y solo cambian las tintas. Comentarios y docstrings en comment,
// keywords y operadores en pink, strings en yellow, funciones en green, clases
// y builtins en cyan, constantes en purple y parametros en orange
const THEME: PrismTheme = {
  plain: { color: 'var(--ink)', backgroundColor: 'transparent' },
  styles: [
    { types: ['comment', 'triple-quoted-string'], style: { color: 'var(--code-comment)' } },
    { types: ['keyword', 'operator'], style: { color: 'var(--code-keyword)' } },
    { types: ['string', 'char'], style: { color: 'var(--code-string)' } },
    { types: ['function', 'decorator'], style: { color: 'var(--code-function)' } },
    { types: ['class-name', 'builtin'], style: { color: 'var(--code-class)' } },
    { types: ['number', 'constant', 'boolean'], style: { color: 'var(--code-constant)' } },
    { types: ['parameter'], style: { color: 'var(--code-parameter)' } },
  ],
}

// `highlights`: lineas del archivo que van subrayadas en --signal
type CodeBlockProps = { code: string; startLine: number; label: string; highlights?: LineRange[] }

export default function CodeBlock({ code, startLine, label, highlights = [] }: CodeBlockProps) {
  const lastLine = startLine + code.split('\n').length - 1
  // El ancho del numero mas largo, para que el codigo arranque en la misma columna
  const gutter = `${String(lastLine).length}ch`
  const marked = (line: number) => highlights.some(({ start, end }) => start <= line && line <= end)

  return (
    <Highlight theme={THEME} code={code.replace(/\n$/, '')} language="python">
      {({ style, tokens, getLineProps, getTokenProps }) => (
        // Se scrollea adentro de su bloque, asi que tiene que poder enfocarse
        <pre
          tabIndex={0}
          aria-label={label}
          style={style}
          className="mt-3 max-h-112 overflow-auto rounded-xs border border-rule py-3 font-mono text-sm leading-relaxed"
        >
          <code className="block min-w-max">
            {tokens.map((line, index) => {
              const isMarked = marked(startLine + index)
              return (
                <div key={index} {...getLineProps({ line, className: 'flex' })}>
                  {/* El numero de linea del archivo original, fijo al scrollear de costado */}
                  <span
                    aria-hidden="true"
                    style={{ minWidth: gutter }}
                    className={`sticky left-0 box-content shrink-0 bg-ground pr-4 pl-3 text-right select-none ${isMarked ? 'text-signal' : 'text-pencil'}`}
                  >
                    {startLine + index}
                  </span>
                  <span className="pr-4 whitespace-pre">
                    {line.map((token, key) => (
                      <span
                        key={key}
                        {...getTokenProps({
                          token,
                          // La sangria no se subraya: solo el codigo
                          className:
                            isMarked && token.content.trim()
                              ? 'underline decoration-signal decoration-2 underline-offset-4'
                              : undefined,
                        })}
                      />
                    ))}
                  </span>
                </div>
              )
            })}
          </code>
        </pre>
      )}
    </Highlight>
  )
}
