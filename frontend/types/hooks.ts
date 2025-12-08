/**
 * Shared types for hooks across the application.
 * Consolidates common type definitions to avoid duplication.
 */

/**
 * Toast notification type.
 * Used across multiple hooks and components for consistent toast styling.
 * - 'confirmation': Subtle feedback for UI setting changes (bottom-center, fast dismiss)
 * - 'info': General information (bottom-center)
 * - 'success': Positive feedback (bottom-center)
 * - 'error': Important errors requiring attention (top-right)
 */
export type ToastType = 'info' | 'success' | 'error' | 'confirmation';
