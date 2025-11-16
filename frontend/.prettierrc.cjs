/** @type {import("prettier").Config} */
module.exports = {
  singleQuote: true,
  semi: true,
  trailingComma: 'es5',
  printWidth: 90,
  tabWidth: 2,
  bracketSpacing: true,
  arrowParens: 'always',
  plugins: ['prettier-plugin-tailwindcss'],
};
