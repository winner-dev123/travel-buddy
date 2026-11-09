import js from '@eslint/js';
import nextVitals from 'eslint-config-next/core-web-vitals';
import prettier from 'eslint-config-prettier';
import globals from 'globals';
import tseslint from 'typescript-eslint';

const WEB = 'apps/web/**/*.{ts,tsx}';

export default [
  {
    ignores: [
      '**/node_modules/**',
      '**/.next/**',
      '**/coverage/**',
      '**/playwright-report/**',
      '**/test-results/**',
      '**/next-env.d.ts',
      'packages/domain-types/src/generated.ts',
      'apps/web/public/vendor/**',
      // Owned by other work streams with their own tooling:
      'backend/**',
      'mobile/**',
      'contracts/**',
      'infra/**',
      'docs/**',
    ],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  ...nextVitals.map((config) => ({ ...config, files: [WEB] })),
  {
    settings: { next: { rootDir: 'apps/web' } },
  },
  {
    files: ['**/*.{ts,tsx}'],
    rules: {
      '@typescript-eslint/consistent-type-imports': ['error', { fixStyle: 'inline-type-imports' }],
      '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_', varsIgnorePattern: '^_' }],
      'no-console': ['warn', { allow: ['warn', 'error'] }],
    },
  },
  {
    // Architectural boundaries (docs/web/01 §7.1, ADR-0010).
    files: ['apps/web/src/**/*.{ts,tsx}'],
    ignores: ['apps/web/src/server/**', 'apps/web/src/app/\\[locale\\]/(auth)/dev/**', 'apps/web/src/**/*.test.{ts,tsx}'],
    rules: {
      'no-restricted-imports': [
        'error',
        {
          patterns: [
            { group: ['@travelbuddy/api-client/mock', '@travelbuddy/api-client/mock/*'], message: 'The mock adapter is server-only (docs/web/01 §7.1). Import it from src/server only.' },
          ],
        },
      ],
    },
  },
  {
    files: ['apps/web/src/**/*.{ts,tsx}'],
    // Rule configs override (not merge) across blocks, so this block repeats the mock ban and the
    // server/dev/test exemptions; it adds the admin boundary for everything outside the admin area.
    ignores: [
      'apps/web/src/app/\\[locale\\]/admin/**',
      'apps/web/src/features/admin/**',
      'apps/web/src/server/**',
      'apps/web/src/app/\\[locale\\]/(auth)/dev/**',
      'apps/web/src/**/*.test.{ts,tsx}',
    ],
    rules: {
      'no-restricted-imports': [
        'error',
        {
          patterns: [
            { group: ['@travelbuddy/api-client/mock', '@travelbuddy/api-client/mock/*'], message: 'The mock adapter is server-only (docs/web/01 §7.1). Import it from src/server only.' },
            { group: ['**/features/admin/**'], message: 'Admin code stays inside the admin area (ADR-0010).' },
          ],
        },
      ],
    },
  },
  {
    files: ['**/*.{js,mjs,cjs}'],
    languageOptions: { globals: { ...globals.node, ...globals.browser } },
  },
  prettier,
];
