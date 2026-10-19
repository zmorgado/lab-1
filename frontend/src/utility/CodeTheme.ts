import type { PrismTheme } from 'prism-react-renderer'

// Las tintas de sintaxis del Om Theme (A Darker Dracula Theme), leidas de los
// tokens: el codigo va sobre el papel de la pagina, asi que el fondo queda
// transparente y solo cambian las tintas. Comentarios y docstrings en comment,
// keywords y operadores en pink, strings y f-strings en yellow, funciones en
// green, clases y builtins en cyan, constantes en purple y parametros en orange
export const CODE_THEME: PrismTheme = {
  plain: { color: 'var(--ink)', backgroundColor: 'transparent' },
  styles: [
    { types: ['comment', 'triple-quoted-string'], style: { color: 'var(--code-comment)' } },
    { types: ['keyword', 'operator'], style: { color: 'var(--code-keyword)' } },
    { types: ['string', 'char', 'string-interpolation'], style: { color: 'var(--code-string)' } },
    { types: ['function', 'decorator'], style: { color: 'var(--code-function)' } },
    { types: ['class-name', 'builtin'], style: { color: 'var(--code-class)' } },
    { types: ['number', 'constant', 'boolean'], style: { color: 'var(--code-constant)' } },
    { types: ['parameter'], style: { color: 'var(--code-parameter)' } },
  ],
}
