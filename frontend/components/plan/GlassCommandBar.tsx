'use client';

import { CheckCircle2, Lock } from 'lucide-react';
import { useEffect, useState } from 'react';

import type { ViewName } from '@/hooks/useViewNavigation';
import { cn } from '@/lib/utils';
import type { PlanningPhase,ViewMode } from '@/types/plan-envelope';

// =============================================================================
// Types
// =============================================================================

interface GlassCommandBarProps {
  // === Two-Mode System (New) ===
  /** Current active mode */
  activeMode?: ViewMode;
  /** Navigate to a mode */
  onModeNavigate?: (mode: ViewMode) => void;
  /** Whether booking mode is unlocked */
  canViewBooking?: boolean;
  /** Current planning phase for progress indicator */
  planningPhase?: PlanningPhase;
  /** Progress percentage (0-100) */
  planningProgress?: number;

  // === Legacy API (backward compatibility) ===
  activeView?: ViewName;
  canViewSetup?: boolean;
  canViewPlan?: boolean;
  canViewBook?: boolean;
  isGenerating?: boolean;
  onNavigate?: (view: ViewName) => void;
}

// Two-mode steps
const MODE_STEPS: { key: ViewMode; label: string }[] = [
  { key: 'planning', label: 'Planning' },
  { key: 'booking', label: 'Booking' },
];

// Legacy three-mode steps
const LEGACY_STEPS: { key: ViewName; label: string }[] = [
  { key: 'setup', label: 'Setup' },
  { key: 'plan', label: 'Plan' },
  { key: 'book', label: 'Book' },
];

/**
 * GlassCommandBar
 *
 * @deprecated Use ModeIndicator from PlanningProgress.tsx instead.
 * This component is kept for backward compatibility only.
 *
 * Premium glassmorphism navigation pill that floats over the hero image.
 *
 * Supports two modes:
 * 1. Two-Mode System (new): PLANNING + BOOKING with progress indicator
 * 2. Legacy Three-Mode: setup + plan + book (for backward compatibility)
 *
 * NOTE: The three-mode system (setup/plan/book) is deprecated.
 * Frontend now uses two-mode system (planning/booking) where content
 * renders based on data availability, not explicit mode states.
 *
 * Features:
 * - Hybrid mobile behavior: floating at top, sticky on scroll
 * - Visual states: active, completed, locked, generating
 * - Planning progress indicator in two-mode system
 */
export function GlassCommandBar({
  // New two-mode props
  activeMode,
  onModeNavigate,
  canViewBooking,
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  planningPhase: _planningPhase,
  planningProgress,
  // Legacy props
  activeView,
  canViewSetup = true,
  canViewPlan = false,
  canViewBook = false,
  isGenerating = false,
  onNavigate,
}: GlassCommandBarProps) {
  const [isScrolled, setIsScrolled] = useState(false);

  // Detect which mode to use: two-mode (new) or three-mode (legacy)
  const useTwoModeSystem = activeMode !== undefined && onModeNavigate !== undefined;

  // Hybrid scroll behavior: floating -> sticky on scroll
  useEffect(() => {
    const threshold = 280; // Hero image height
    const handleScroll = () => {
      setIsScrolled(window.scrollY > threshold);
    };
    window.addEventListener('scroll', handleScroll, { passive: true });
    return () => window.removeEventListener('scroll', handleScroll);
  }, []);

  // === Two-Mode System Rendering ===
  if (useTwoModeSystem) {
    return (
      <div
        className={cn(
          'transition-all duration-500 ease-[cubic-bezier(0.32,0.72,0,1)] z-50 pointer-events-auto',
          isScrolled
            ? [
                'fixed top-0 left-0 right-0 flex justify-center py-2 backdrop-blur-md shadow-sm',
                'bg-white/90 border-b border-zinc-200/80',
                'dark:bg-background/80 dark:border-b dark:border-white/5',
              ]
            : 'relative -mt-5 flex justify-center'
        )}
      >
        {/* Main Container with Mode Pills + Progress */}
        <div
          className={cn(
            'relative flex items-center gap-3 p-1.5 transition-all duration-300',
            !isScrolled && [
              'rounded-full px-3 border backdrop-blur-xl',
              'bg-zinc-100 border-zinc-200',
              'dark:bg-black/40 dark:border-white/10 dark:shadow-2xl',
            ]
          )}
        >
          {/* Mode Pills */}
          <div className="flex items-center gap-1">
            {MODE_STEPS.map((step) => {
              const isActive = activeMode === step.key;
              const isLocked = step.key === 'booking' && !canViewBooking;

              return (
                <button
                  key={step.key}
                  type="button"
                  onClick={() => !isLocked && onModeNavigate(step.key)}
                  disabled={isLocked}
                  className={cn(
                    'relative flex items-center gap-2 px-5 py-2.5 rounded-full text-xs font-bold uppercase tracking-widest transition-all duration-200',
                    // Active state
                    isActive && [
                      'bg-white shadow-[0_1px_3px_0_rgba(0,0,0,0.1),0_1px_2px_-1px_rgba(0,0,0,0.1)] ring-1 ring-black/5',
                      'text-zinc-950 font-bold',
                      'dark:bg-white dark:text-zinc-950 dark:ring-0',
                      'dark:shadow-[0_0_15px_-3px_rgba(255,255,255,0.4)]',
                    ],
                    // Default state
                    !isActive && !isLocked && [
                      'text-zinc-500 hover:text-zinc-800 hover:bg-zinc-100/80',
                      'dark:text-white/60 dark:hover:text-white dark:hover:bg-white/10',
                    ],
                    // Locked state
                    isLocked && [
                      'opacity-40 cursor-not-allowed',
                      'text-zinc-400',
                      'dark:text-white/40',
                    ]
                  )}
                >
                  {isLocked && <Lock className="w-3.5 h-3.5" />}
                  {step.label}
                </button>
              );
            })}
          </div>

          {/* Progress Indicator (Planning mode only) */}
          {activeMode === 'planning' && planningProgress !== undefined && (
            <div className="flex items-center gap-2 px-2">
              {/* Progress bar */}
              <div className="h-1.5 w-16 overflow-hidden rounded-full bg-zinc-300/50 dark:bg-white/10">
                <div
                  className="h-full bg-emerald-500 transition-all duration-500"
                  style={{ width: `${planningProgress}%` }}
                />
              </div>
              <span className="text-[10px] tabular-nums text-zinc-500 dark:text-white/50">
                {planningProgress}%
              </span>
            </div>
          )}
        </div>
      </div>
    );
  }

  // === Legacy Three-Mode System Rendering ===
  // Determine unlock state for each step
  const getStepState = (key: ViewName) => {
    const isActive = activeView === key;
    const isLocked =
      (key === 'plan' && !canViewPlan) ||
      (key === 'book' && !canViewBook) ||
      (key === 'setup' && !canViewSetup);

    // Setup is "completed" once user has left it (plan generation started)
    const isCompleted = key === 'setup' && !canViewSetup && activeView !== 'setup';

    // Plan is "generating" state
    const isGeneratingStep = key === 'plan' && isGenerating;

    return { isActive, isLocked, isCompleted, isGeneratingStep };
  };

  // Get status icon for step (null for generating - uses custom spinner)
  const getStatusIcon = (key: ViewName) => {
    const { isCompleted, isLocked, isGeneratingStep } = getStepState(key);

    if (isGeneratingStep) return null; // Custom spinner rendered separately
    if (isCompleted) return CheckCircle2;
    if (isLocked) return Lock;
    return null;
  };

  return (
    <div
      className={cn(
        'transition-all duration-500 ease-[cubic-bezier(0.32,0.72,0,1)] z-50 pointer-events-auto',
        isScrolled
          ? [
              'fixed top-0 left-0 right-0 flex justify-center py-2 backdrop-blur-md shadow-sm',
              'bg-white/90 border-b border-zinc-200/80',
              'dark:bg-background/80 dark:border-b dark:border-white/5',
            ]
          : 'relative -mt-5 flex justify-center'
      )}
    >
      {/* Main Pill Container - Frosted Ice (Light) / Smoked Glass (Dark) */}
      <div
        className={cn(
          'relative flex items-center gap-1 p-1.5 transition-all duration-300',
          !isScrolled && [
            'rounded-full px-2 border backdrop-blur-xl',
            'bg-zinc-100 border-zinc-200',
            'dark:bg-black/40 dark:border-white/10 dark:shadow-2xl',
          ]
        )}
      >
        {LEGACY_STEPS.map((step) => {
          const { isActive, isLocked, isCompleted, isGeneratingStep } = getStepState(step.key);
          const StatusIcon = getStatusIcon(step.key);

          return (
            <button
              key={step.key}
              type="button"
              onClick={() => !isLocked && onNavigate?.(step.key)}
              disabled={isLocked}
              className={cn(
                'relative flex items-center gap-2 px-5 py-2.5 rounded-full text-xs font-bold uppercase tracking-widest transition-all duration-200',
                // Active state
                isActive && [
                  'bg-white shadow-[0_1px_3px_0_rgba(0,0,0,0.1),0_1px_2px_-1px_rgba(0,0,0,0.1)] ring-1 ring-black/5',
                  'text-zinc-950 font-bold',
                  'dark:bg-white dark:text-zinc-950 dark:ring-0',
                  'dark:shadow-[0_0_15px_-3px_rgba(255,255,255,0.4)]',
                ],
                // Completed state
                isCompleted && !isActive && 'text-emerald-600 dark:text-emerald-400',
                // Generating state
                isGeneratingStep && 'generating-pulse text-emerald-600 dark:text-emerald-400',
                // Default state
                !isActive && !isCompleted && !isLocked && [
                  'text-zinc-500 hover:text-zinc-800 hover:bg-zinc-100/80',
                  'dark:text-white/60 dark:hover:text-white dark:hover:bg-white/10',
                ],
                // Locked state
                isLocked && [
                  'opacity-40 cursor-not-allowed',
                  'text-zinc-400 hover:bg-transparent hover:text-zinc-400',
                  'dark:text-white/40 dark:hover:bg-transparent dark:hover:text-white/40',
                ]
              )}
            >
              {/* Custom circular spinner for generating state */}
              {isGeneratingStep && (
                <span className="relative w-3.5 h-3.5">
                  <span className="absolute inset-0 rounded-full border-2 border-emerald-500/30 dark:border-emerald-400/30" />
                  <span className="absolute inset-0 rounded-full border-2 border-transparent border-t-emerald-500 dark:border-t-emerald-400 animate-spin" />
                </span>
              )}
              {/* Status icons for other states */}
              {StatusIcon && (
                <StatusIcon
                  className={cn(
                    'w-3.5 h-3.5',
                    isCompleted && 'text-emerald-600 dark:text-emerald-400'
                  )}
                />
              )}
              {step.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}

export default GlassCommandBar;
