import { defineConfig, mergeConfig } from 'vitest/config'
import viteConfig from './vite.config.ts'

// Reutiliza vite.config.ts (alias '@', plugins) en vez de repetirlo.
export default mergeConfig(
  viteConfig,
  defineConfig({
    test: {
      // 'node' cubre las funciones puras de hoy; un test de componente o hook
      // que toque el DOM va a necesitar sumar jsdom/happy-dom antes de andar.
      environment: 'node',
    },
  }),
)
