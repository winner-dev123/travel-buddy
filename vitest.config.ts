import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    projects: [
      {
        test: {
          name: 'packages',
          include: ['packages/*/src/**/*.test.ts'],
          environment: 'node',
        },
      },
      'apps/web/vitest.config.ts',
    ],
  },
});
