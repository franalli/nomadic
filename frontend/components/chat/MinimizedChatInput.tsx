'use client';

import { AnimatePresence, motion } from 'framer-motion';
import { Loader2, Send } from 'lucide-react';
import { memo, useCallback, useEffect, useRef, useState } from 'react';

import { useMobileMode } from '@/contexts/MobileModeContext';
import { cn } from '@/lib/utils';

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

interface MinimizedChatInputProps {
  /** Callback when user sends a message */
  onSendMessage: (message: string) => void;
  /** Whether message is currently being processed */
  isProcessing?: boolean;
  /** Placeholder text for the input */
  placeholder?: string;
  /** Whether input is disabled */
  disabled?: boolean;
  className?: string;
}

// ─────────────────────────────────────────────────────────────────────────────
// Animation Variants
// ─────────────────────────────────────────────────────────────────────────────

const inputVariants = {
  hidden: {
    opacity: 0,
    y: 10,
  },
  visible: {
    opacity: 1,
    y: 0,
    transition: {
      duration: 0.2,
      ease: 'easeOut',
    },
  },
  exit: {
    opacity: 0,
    y: 10,
    transition: {
      duration: 0.15,
    },
  },
};

const toastVariants = {
  hidden: { opacity: 0, y: 20, scale: 0.95 },
  visible: {
    opacity: 1,
    y: 0,
    scale: 1,
    transition: { type: 'spring', stiffness: 400, damping: 25 },
  },
  exit: {
    opacity: 0,
    y: -10,
    scale: 0.95,
    transition: { duration: 0.2 },
  },
};

// ─────────────────────────────────────────────────────────────────────────────
// Component
// ─────────────────────────────────────────────────────────────────────────────

/**
 * MinimizedChatInput - Compact chat input bar for Plan/Book tabs.
 *
 * Allows users to send commands while viewing the plan without switching tabs.
 * Messages are sent immediately and visual feedback is provided via toast.
 */
function MinimizedChatInputInner({
  onSendMessage,
  isProcessing = false,
  placeholder = 'Type a command...',
  disabled = false,
  className,
}: MinimizedChatInputProps) {
  const { mode, isDesktop } = useMobileMode();
  const [inputValue, setInputValue] = useState('');
  const [showSentToast, setShowSentToast] = useState(false);
  const toastTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Cleanup timer on unmount
  useEffect(() => {
    return () => {
      if (toastTimerRef.current) {
        clearTimeout(toastTimerRef.current);
      }
    };
  }, []);

  // Only show on mobile when in plan mode (not in planner/chat mode)
  const shouldShow = !isDesktop && mode === 'plan';

  const handleSubmit = useCallback(
    (e?: React.FormEvent) => {
      e?.preventDefault();

      const trimmedValue = inputValue.trim();
      if (!trimmedValue || disabled || isProcessing) return;

      // Send the message
      onSendMessage(trimmedValue);

      // Clear input
      setInputValue('');

      // Show sent toast
      setShowSentToast(true);
      if (toastTimerRef.current) {
        clearTimeout(toastTimerRef.current);
      }
      toastTimerRef.current = setTimeout(() => setShowSentToast(false), 2000);
    },
    [inputValue, disabled, isProcessing, onSendMessage]
  );

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        handleSubmit();
      }
    },
    [handleSubmit]
  );

  if (!shouldShow) {
    return null;
  }

  const canSend = inputValue.trim().length > 0 && !disabled && !isProcessing;

  return (
    <>
      {/* Input Bar */}
      <motion.div
        className={cn(
          'fixed left-0 right-0 z-[1001]',
          // Position above tab bar using CSS variable
          'bottom-[calc(var(--mobile-tab-bar-height,68px)+env(safe-area-inset-bottom))]',
          'px-4 pb-2',
          'lg:hidden',
          className
        )}
        variants={inputVariants}
        initial="hidden"
        animate="visible"
        exit="exit"
      >
        <form
          onSubmit={handleSubmit}
          className={cn(
            'flex items-center gap-2',
            'px-3 py-2',
            'rounded-xl',
            'bg-background/95 backdrop-blur-md',
            'border border-border/60',
            'shadow-[0_-2px_10px_rgba(0,0,0,0.06)]',
            'dark:shadow-[0_-2px_10px_rgba(0,0,0,0.2)]'
          )}
        >
          <input
            type="text"
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={placeholder}
            disabled={disabled || isProcessing}
            className={cn(
              'flex-1 bg-transparent',
              'text-sm text-foreground placeholder:text-muted-foreground/60',
              'outline-none',
              'disabled:opacity-50 disabled:cursor-not-allowed'
            )}
            aria-label="Send a command"
          />

          <button
            type="submit"
            disabled={!canSend}
            className={cn(
              'flex items-center justify-center',
              'w-8 h-8 rounded-lg',
              'transition-all duration-150',
              canSend
                ? 'bg-emerald-500 text-white hover:bg-emerald-600 active:scale-95'
                : 'bg-muted text-muted-foreground cursor-not-allowed'
            )}
            aria-label="Send message"
          >
            {isProcessing ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Send className="h-4 w-4" />
            )}
          </button>
        </form>
      </motion.div>

      {/* Sent Toast */}
      <AnimatePresence>
        {showSentToast && (
          <motion.div
            className={cn(
              'fixed left-1/2 -translate-x-1/2 z-[1002]',
              // Position above the input bar using CSS variables
              'bottom-[calc(var(--mobile-tab-bar-height,68px)+var(--mobile-minimized-input-height,56px)+env(safe-area-inset-bottom))]',
              'px-4 py-2 rounded-full',
              'bg-emerald-500 text-white',
              'text-sm font-medium',
              'shadow-lg',
              'lg:hidden'
            )}
            variants={toastVariants}
            initial="hidden"
            animate="visible"
            exit="exit"
          >
            Message sent
          </motion.div>
        )}
      </AnimatePresence>
    </>
  );
}

export const MinimizedChatInput = memo(MinimizedChatInputInner);
