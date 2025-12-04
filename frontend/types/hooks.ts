/**
 * Shared types for hooks across the application.
 * Consolidates common type definitions to avoid duplication.
 */

/**
 * Toast notification type.
 * Used across multiple hooks and components for consistent toast styling.
 */
export type ToastType = 'info' | 'success' | 'error';

/**
 * Interface for chat panel actions exposed to other components.
 * Used to programmatically add messages from hooks.
 */
export interface ChatPanelActions {
  addAssistantMessage: (message: string) => void;
}
