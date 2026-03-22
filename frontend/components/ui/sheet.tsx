'use client';
/* eslint no-unused-vars: ["error", { "args": "none" }] */

import * as React from 'react';

interface SheetContextValue {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

const SheetContext = React.createContext<SheetContextValue | undefined>(undefined);

export function useSheet() {
  const context = React.useContext(SheetContext);
  if (!context) {
    throw new Error('Sheet components must be used within a Sheet');
  }
  return context;
}

interface SheetProps {
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  children: React.ReactNode;
}

function Sheet({ open = false, onOpenChange, children }: SheetProps) {
  const handleOpenChange = React.useCallback(
    (value: boolean) => {
      onOpenChange?.(value);
    },
    [onOpenChange]
  );

  const contextValue = React.useMemo(
    () => ({ open, onOpenChange: handleOpenChange }),
    [open, handleOpenChange]
  );

  return (
    <SheetContext.Provider value={contextValue}>
      {children}
    </SheetContext.Provider>
  );
}

export { Sheet };
export { SheetClose, SheetContent, SheetHeader, SheetTitle } from './SheetParts';
