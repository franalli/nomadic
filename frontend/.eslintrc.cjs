/** @type {import("eslint").Linter.Config} */
module.exports = {
  root: true,
  parser: '@typescript-eslint/parser',
  parserOptions: {
    ecmaVersion: 'latest',
    sourceType: 'module',
    ecmaFeatures: { jsx: true },
  },
  env: {
    browser: true,
    node: true,
    es2021: true,
  },
  settings: {
    react: {
      version: 'detect',
    },
    'import/resolver': {
      node: {
        extensions: ['.js', '.jsx', '.ts', '.tsx'],
      },
      typescript: {},
    },
  },
  plugins: ['@typescript-eslint', 'react', 'import', 'tailwindcss', 'simple-import-sort'],
  extends: [
    'next/core-web-vitals',
    'eslint:recommended',
    'plugin:@typescript-eslint/recommended',
    'plugin:react/recommended',
    'plugin:import/recommended',
    'plugin:import/typescript',
    'plugin:tailwindcss/recommended',
    'prettier',
  ],
  rules: {
    // General
    'no-console': ['warn', { allow: ['warn', 'error'] }],
    'no-debugger': 'warn',

    // TypeScript
    '@typescript-eslint/no-unused-vars': [
      'warn',
      { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
    ],

    // React
    'react/react-in-jsx-scope': 'off', // Next.js handles this
    'react/prop-types': 'off',

    // Import sorting (simple-import-sort)
    'import/order': 'off',
    'sort-imports': 'off',
    'simple-import-sort/imports': 'error',
    'simple-import-sort/exports': 'error',

    // Tailwind: let plugin validate class names; don't be too strict
    'tailwindcss/classnames-order': 'off', // Prettier plugin will handle order
    'tailwindcss/no-custom-classname': 'off', // avoid fighting BEM/custom names

    // Next specific
    '@next/next/no-img-element': 'off', // you’re using <img>; can flip later
  },
  ignorePatterns: [
    'node_modules/',
    '.next/',
    'out/',
    'dist/',
    'coverage/',
    '*.config.cjs',
    '*.config.mjs',
  ],
};
