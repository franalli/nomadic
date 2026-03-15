'use client';

import type { ReactNode } from 'react';

export const BACKDROP_INITIAL = { opacity: 0 };
export const BACKDROP_ANIMATE = { opacity: 1 };
export const BACKDROP_EXIT = { opacity: 0 };
export const BACKDROP_TRANSITION = { duration: 0.15 };
export const MODAL_INITIAL = { opacity: 0, scale: 0.95, y: 10 };
export const MODAL_ANIMATE = { opacity: 1, scale: 1, y: 0 };
export const MODAL_EXIT = { opacity: 0, scale: 0.95, y: 10 };
export const MODAL_TRANSITION = { type: 'spring' as const, damping: 30, stiffness: 400 };
export const MOBILE_BACKDROP_TRANSITION = { duration: 0.2 };
export const MOBILE_SHEET_INITIAL = { y: '100%' };
export const MOBILE_SHEET_ANIMATE = { y: 0 };
export const MOBILE_SHEET_EXIT = { y: '100%' };
export const MOBILE_SHEET_TRANSITION = {
  type: 'spring' as const,
  damping: 30,
  stiffness: 300,
};

export interface BaseSheetProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  hint?: string;
  children: ReactNode;
  footer?: ReactNode;
  className?: string;
  maxWidth?: 'sm' | 'md' | 'lg' | 'xl' | '2xl';
}
