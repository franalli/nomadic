/** @type {import("eslint").Linter.Config} */
const path = require('path');

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
  extends: [
    'eslint:recommended',
    'plugin:@typescript-eslint/recommended',
    'plugin:import/recommended',
    'plugin:import/typescript',
    'plugin:react-hooks/recommended',
    'plugin:tailwindcss/recommended',
    'prettier',
  ],
  plugins: ['simple-import-sort', 'react-hooks'],
  rules: {
    'no-console': ['warn', { allow: ['warn', 'error'] }],
    'no-debugger': 'warn',
    'import/order': 'off',
    'sort-imports': 'off',
    'simple-import-sort/imports': 'error',
    'simple-import-sort/exports': 'error',
    'tailwindcss/classnames-order': 'off',
    'tailwindcss/no-custom-classname': 'off',
    'tailwindcss/enforces-shorthand': 'off',
    'react-hooks/set-state-in-effect': 'off',
    '@next/next/no-img-element': 'off',
  },
  settings: {
    'import/resolver': {
      node: {
        extensions: ['.js', '.jsx', '.ts', '.tsx'],
        paths: ['.'],
      },
      typescript: {
        // Ensure the resolver picks up our baseUrl/path aliases from the
        // project tsconfig when the workspace root isn't the Next app folder.
        project: [path.join(__dirname, 'tsconfig.json')],
      },
    },
  },
  ignorePatterns: ['node_modules/', '.next/', 'out/', 'dist/', 'coverage/'],
};
