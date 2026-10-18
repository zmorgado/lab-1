import { Highlight, type PrismTheme } from 'prism-react-renderer'

// El tema lee los tokens, sin paleta de la libreria: comentarios y docstrings en
// pencil, keywords en 600, todo lo demas en ink
const THEME: PrismTheme = {
  plain: { color: 'var(--ink)', backgroundColor: 'transparent' },
  styles: [
    { types: ['comment', 'triple-quoted-string'], style: { color: 'var(--pencil)' } },
    { types: ['keyword', 'boolean'], style: { fontWeight: '600' } },
  ],
}

type CodeBlockProps = { code: string; startLine: number; label: string }

export default function CodeBlock({ code, startLine, label }: CodeBlockProps) {
  const lastLine = startLine + code.split('\n').length - 1
  // El ancho del numero mas largo, para que el codigo arranque en la misma columna
  const gutter = `${String(lastLine).length}ch`

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
            {tokens.map((line, index) => (
              <div key={index} {...getLineProps({ line, className: 'flex' })}>
                {/* El numero de linea del archivo original, fijo al scrollear de costado */}
                <span
                  aria-hidden="true"
                  style={{ minWidth: gutter }}
                  className="sticky left-0 box-content shrink-0 bg-ground pr-4 pl-3 text-right text-pencil select-none"
                >
                  {startLine + index}
                </span>
                <span className="pr-4 whitespace-pre">
                  {line.map((token, key) => (
                    <span key={key} {...getTokenProps({ token })} />
                  ))}
                </span>
              </div>
            ))}
          </code>
        </pre>
      )}
    </Highlight>
  )
}
