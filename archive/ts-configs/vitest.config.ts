import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    globals: true,
    environment: 'node',
    include: ['tests/**/*.test.ts'],
    coverage: {
      provider: 'v8',
      include: ['src/**/*.ts'],
      exclude: ['src/infrastructure/main.ts'],
    },
    testTimeout: 30_000,
    hookTimeout: 10_000,
  },
  resolve: {
    alias: {
      '@entities': './src/entities',
      '@use-cases': './src/use-cases',
      '@adapters': './src/adapters',
      '@infrastructure': './src/infrastructure',
    },
  },
});
