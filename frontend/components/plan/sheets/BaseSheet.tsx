'use client';
/* eslint no-unused-vars: ["error", { "args": "none" }] */

import { memo } from 'react';

import { useIsDesktop } from '@/hooks/useIsDesktop';

import type { BaseSheetProps } from './BaseSheet.shared';
import { BaseSheetDesktopDialog } from './BaseSheetDesktopDialog';
import { BaseSheetMobileSheet } from './BaseSheetMobileSheet';

function BaseSheetInner(props: BaseSheetProps) {
  const isDesktop = useIsDesktop();
  return isDesktop ? <BaseSheetDesktopDialog {...props} /> : <BaseSheetMobileSheet {...props} />;
}

export const BaseSheet = memo(BaseSheetInner);

export default BaseSheet;
