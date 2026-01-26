'use client';

import { AnimatePresence, motion } from 'framer-motion';
import { ArrowRight, Loader2, Sparkles } from 'lucide-react';
import { memo } from 'react';

import { useMobileMode } from '@/contexts/MobileModeContext';
import { cn } from '@/lib/utils';

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

interface FloatingBuildButtonProps {
  /** Whether the button should be visible */
  visible: boolean;
  /** Callback when button is clicked */
  onClick: () => void;
  /** Whether plan generation is in progress */
  isGenerating?: boolean;
  /** Whether user has ever had a plan generated (changes label) */
  hasEverHadPlan?: boolean;
  className?: string;
}

// ─────────────────────────────────────────────────────────────────────────────
// Animation Variants
// ─────────────────────────────────────────────────────────────────────────────

const buttonVariants = {
  hidden: {
    opacity: 0,
    y: 20,
    scale: 0.95,
  },
  visible: {
    opacity: 1,
    y: 0,
    scale: 1,
    transition: {
      type: 'spring',
      stiffness: 400,
      damping: 25,
    },
  },
  exit: {
    opacity: 0,
    y: 20,
    scale: 0.95,
    transition: {
      duration: 0.15,
    },
  },
};

// ─────────────────────────────────────────────────────────────────────────────
// Component
// ─────────────────────────────────────────────────────────────────────────────

/**
 * FloatingBuildButton - Mobile FAB for "Build Trip Plan".
 *
 * Appears above the chat input when all required fields are set.
 * Provides a clear call-to-action to trigger plan generation.
 */
function FloatingBuildButtonInner({
  visible,
  onClick,
  isGenerating = false,
  hasEverHadPlan = false,
  className,
}: FloatingBuildButtonProps) {
  const { isDesktop, activeTab } = useMobileMode();

  // Only show on mobile, in chat tab
  if (isDesktop || activeTab !== 'chat') {
    return null;
  }

  const buttonLabel = hasEverHadPlan ? 'Update Plan' : 'Build Trip Plan';

  return (
    <AnimatePresence>
      {visible && !isGenerating && (
        <motion.div
          key="floating-build-button"
          className={cn(
            'fixed left-4 right-4 z-[900]',
            'bottom-[calc(64px+env(safe-area-inset-bottom))]', // Above chat input
            'lg:hidden',
            className
          )}
          variants={buttonVariants}
          initial="hidden"
          animate="visible"
          exit="exit"
        >
          <button
            type="button"
            onClick={onClick}
            disabled={isGenerating}
            className={cn(
              'w-full flex items-center justify-center gap-2',
              'px-6 py-3.5 rounded-xl',
              'font-semibold text-base',
              'transition-all duration-200',
              // Gradient background
              'bg-gradient-to-r from-amber-500 to-orange-500',
              'text-white',
              'shadow-[0_4px_20px_rgba(245,158,11,0.35)]',
              // Hover/active states
              'hover:shadow-[0_6px_24px_rgba(245,158,11,0.45)]',
              'hover:brightness-105',
              'active:scale-[0.98]',
              // Disabled state
              'disabled:opacity-50 disabled:cursor-not-allowed'
            )}
          >
            {isGenerating ? (
              <>
                <Loader2 className="h-5 w-5 animate-spin" />
                <span>Building...</span>
              </>
            ) : (
              <>
                <Sparkles className="h-5 w-5" />
                <span>{buttonLabel}</span>
                <ArrowRight className="h-5 w-5" />
              </>
            )}
          </button>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

export const FloatingBuildButton = memo(FloatingBuildButtonInner);
