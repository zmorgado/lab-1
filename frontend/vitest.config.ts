import { defineConfig, mergeConfig } from 'vitest/config'
import viteConfig from './vite.config.ts'

// Reutiliza vite.config.ts (alias '@', plugins) en vez de repetirlo.
export default mergeConfig(
  viteConfig,
  defineConfig({
    test: {
      // La pagina se prueba renderizada, con el backend stubeado con MSW
      environment: 'jsdom',
    },
  }),
)
