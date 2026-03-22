export type ThemeMode = 'light' | 'dark';

const THEME_MODE: ThemeMode = 'dark';

export const THEME_CLASS = THEME_MODE;

export const isDarkTheme = (): boolean => THEME_MODE === 'dark';
