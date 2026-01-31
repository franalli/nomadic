/**
 * CheckoutSheet
 *
 * The "Hard Gate" checkout flow - collects guest details before payment.
 * Opens a premium sheet with trip recap and guest information form.
 *
 * Flow:
 * 1. User clicks "Continue to Booking" in CheckoutSidebar
 * 2. CheckoutSheet opens with trip summary + guest form
 * 3. User fills in details and clicks "Pay with Stripe"
 * 4. Backend creates Stripe Checkout session
 * 5. User is redirected to Stripe for payment
 */

'use client';

import { AnimatePresence, motion } from 'framer-motion';
import {
  ArrowRight,
  CreditCard,
  Loader2,
  Mail,
  Phone,
  ShieldCheck,
  User,
  X,
} from 'lucide-react';
import { memo, useCallback, useEffect, useState } from 'react';
import { createPortal } from 'react-dom';

import { Button } from '@/components/ui/button';
import { useToast } from '@/components/ui/toast';
import { useMobileMode } from '@/contexts/MobileModeContext';
import { cn } from '@/lib/utils';
import type { Tile } from '@/types/tile';

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

export interface CheckoutSheetProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Selected tiles for booking */
  selectedTiles: Tile[];
  /** Total amount */
  total: number;
  /** Currency code */
  currency?: string;
  /** Trip destination */
  destination?: string;
  /** Trip dates */
  dates?: string;
  /** Number of travelers */
  travelers?: number;
  /** Callback when checkout is submitted */
  onSubmit: (guestDetails: GuestDetails) => Promise<void>;
}

export interface GuestDetails {
  firstName: string;
  lastName: string;
  email: string;
  phone?: string;
}

// ─────────────────────────────────────────────────────────────────────────────
// Component
// ─────────────────────────────────────────────────────────────────────────────

function CheckoutSheetInner({
  open,
  onOpenChange,
  selectedTiles,
  total,
  currency = 'USD',
  destination,
  dates,
  travelers = 1,
  onSubmit,
}: CheckoutSheetProps) {
  const { toast } = useToast();
  const { isDesktop } = useMobileMode();
  const [mounted, setMounted] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Form state
  const [firstName, setFirstName] = useState('');
  const [lastName, setLastName] = useState('');
  const [email, setEmail] = useState('');
  const [phone, setPhone] = useState('');

  // Form validation
  const isFormValid =
    firstName.trim().length > 0 &&
    lastName.trim().length > 0 &&
    email.trim().length > 0 &&
    email.includes('@');

  // Mount check for portal
  useEffect(() => {
    setMounted(true);
  }, []);

  // Reset form when sheet opens
  useEffect(() => {
    if (open) {
      setFirstName('');
      setLastName('');
      setEmail('');
      setPhone('');
      setIsSubmitting(false);
    }
  }, [open]);

  // Format currency
  const formatPrice = (amount: number) => {
    const symbol =
      currency === 'USD' ? '$' : currency === 'EUR' ? '€' : currency === 'GBP' ? '£' : currency;
    return `${symbol}${amount.toLocaleString()}`;
  };

  // Handle submit
  const handleSubmit = useCallback(async () => {
    if (!isFormValid || isSubmitting) return;

    setIsSubmitting(true);
    try {
      await onSubmit({
        firstName: firstName.trim(),
        lastName: lastName.trim(),
        email: email.trim(),
        phone: phone.trim() || undefined,
      });
      // Don't close sheet here - onSubmit will handle navigation
    } catch (error) {
      toast(
        error instanceof Error ? error.message : 'Checkout failed. Please try again.',
        { type: 'error' }
      );
      setIsSubmitting(false);
    }
  }, [isFormValid, isSubmitting, firstName, lastName, email, phone, onSubmit, toast]);

  // Group tiles by category
  const flights = selectedTiles.filter((t) => t.type === 'flight');
  const stays = selectedTiles.filter((t) =>
    ['hotel', 'stay', 'accommodation'].includes(t.type || '')
  );
  const activities = selectedTiles.filter((t) =>
    ['activity', 'experience', 'tour'].includes(t.type || '')
  );

  // Sheet content
  const sheetContent = (
    <AnimatePresence>
      {open && (
        <>
          {/* Backdrop */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="fixed inset-0 z-[99] bg-black/60 backdrop-blur-sm"
            onClick={() => onOpenChange(false)}
          />

          {/* Sheet */}
          <motion.div
            initial={isDesktop ? { opacity: 0, x: 40 } : { opacity: 0, y: '100%' }}
            animate={isDesktop ? { opacity: 1, x: 0 } : { opacity: 1, y: 0 }}
            exit={isDesktop ? { opacity: 0, x: 40 } : { opacity: 0, y: '100%' }}
            transition={{ type: 'spring', damping: 30, stiffness: 300 }}
            className={cn(
              'fixed z-[100] bg-card/95 backdrop-blur-xl shadow-2xl',
              'border-l border-border/50',
              isDesktop
                ? 'right-0 top-0 bottom-0 w-[480px] overflow-hidden'
                : 'left-0 right-0 bottom-0 rounded-t-3xl max-h-[90vh] overflow-hidden'
            )}
          >
            {/* Header */}
            <div className="sticky top-0 z-10 bg-card/90 backdrop-blur-sm border-b border-border/50 px-6 py-4">
              <div className="flex items-center justify-between">
                <div>
                  <h2 className="text-xl font-semibold">Complete Your Booking</h2>
                  <p className="text-sm text-muted-foreground mt-0.5">
                    {destination || 'Your Trip'} • {travelers} traveler
                    {travelers !== 1 ? 's' : ''}
                  </p>
                </div>
                <button
                  onClick={() => onOpenChange(false)}
                  className="p-2 rounded-full hover:bg-muted/50 transition-colors"
                >
                  <X className="w-5 h-5 text-muted-foreground" />
                </button>
              </div>
            </div>

            {/* Scrollable Content */}
            <div className="overflow-y-auto h-[calc(100%-180px)] custom-scrollbar">
              <div className="p-6 space-y-6">
                {/* Trip Summary */}
                <div className="bg-muted/30 rounded-xl p-4 space-y-3">
                  <h3 className="text-sm font-medium text-muted-foreground">Trip Summary</h3>

                  {/* Dates */}
                  {dates && (
                    <div className="flex justify-between text-sm">
                      <span className="text-muted-foreground">Dates</span>
                      <span className="font-medium">{dates}</span>
                    </div>
                  )}

                  {/* Items breakdown */}
                  {flights.length > 0 && (
                    <div className="flex justify-between text-sm">
                      <span className="text-muted-foreground">
                        ✈️ {flights.length} Flight{flights.length > 1 ? 's' : ''}
                      </span>
                      <span className="font-medium">
                        {formatPrice(
                          flights.reduce(
                            (sum, t) => sum + (t.total_inclusive ?? t.price_estimate ?? 0),
                            0
                          )
                        )}
                      </span>
                    </div>
                  )}

                  {stays.length > 0 && (
                    <div className="flex justify-between text-sm">
                      <span className="text-muted-foreground">
                        🏨 {stays.length} Stay{stays.length > 1 ? 's' : ''}
                      </span>
                      <span className="font-medium">
                        {formatPrice(
                          stays.reduce(
                            (sum, t) => sum + (t.total_inclusive ?? t.price_estimate ?? 0),
                            0
                          )
                        )}
                      </span>
                    </div>
                  )}

                  {activities.length > 0 && (
                    <div className="flex justify-between text-sm">
                      <span className="text-muted-foreground">
                        🤿 {activities.length} Activit{activities.length > 1 ? 'ies' : 'y'}
                      </span>
                      <span className="font-medium">
                        {formatPrice(
                          activities.reduce(
                            (sum, t) => sum + (t.total_inclusive ?? t.price_estimate ?? 0),
                            0
                          )
                        )}
                      </span>
                    </div>
                  )}

                  {/* Total */}
                  <div className="flex justify-between pt-3 border-t border-border/50">
                    <span className="font-semibold">Total</span>
                    <span className="font-bold text-lg">{formatPrice(total)}</span>
                  </div>
                </div>

                {/* Guest Details Form */}
                <div className="space-y-4">
                  <h3 className="text-sm font-medium text-muted-foreground">Guest Details</h3>

                  {/* Name row */}
                  <div className="grid grid-cols-2 gap-3">
                    <div className="space-y-1.5">
                      <label htmlFor="firstName" className="text-xs text-muted-foreground">
                        First Name *
                      </label>
                      <div className="relative">
                        <User className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground/50" />
                        <input
                          id="firstName"
                          type="text"
                          value={firstName}
                          onChange={(e) => setFirstName(e.target.value)}
                          placeholder="John"
                          className="w-full pl-9 pr-3 py-2.5 bg-background/50 border border-border/50 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500/30 focus:border-emerald-500/50 transition-colors"
                        />
                      </div>
                    </div>
                    <div className="space-y-1.5">
                      <label htmlFor="lastName" className="text-xs text-muted-foreground">
                        Last Name *
                      </label>
                      <input
                        id="lastName"
                        type="text"
                        value={lastName}
                        onChange={(e) => setLastName(e.target.value)}
                        placeholder="Doe"
                        className="w-full px-3 py-2.5 bg-background/50 border border-border/50 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500/30 focus:border-emerald-500/50 transition-colors"
                      />
                    </div>
                  </div>

                  {/* Email */}
                  <div className="space-y-1.5">
                    <label htmlFor="email" className="text-xs text-muted-foreground">
                      Email Address *
                    </label>
                    <div className="relative">
                      <Mail className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground/50" />
                      <input
                        id="email"
                        type="email"
                        value={email}
                        onChange={(e) => setEmail(e.target.value)}
                        placeholder="john@example.com"
                        className="w-full pl-9 pr-3 py-2.5 bg-background/50 border border-border/50 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500/30 focus:border-emerald-500/50 transition-colors"
                      />
                    </div>
                    <p className="text-[10px] text-muted-foreground/70">
                      Booking confirmation will be sent here
                    </p>
                  </div>

                  {/* Phone (optional) */}
                  <div className="space-y-1.5">
                    <label htmlFor="phone" className="text-xs text-muted-foreground">
                      Phone Number <span className="text-muted-foreground/50">(optional)</span>
                    </label>
                    <div className="relative">
                      <Phone className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground/50" />
                      <input
                        id="phone"
                        type="tel"
                        value={phone}
                        onChange={(e) => setPhone(e.target.value)}
                        placeholder="+1 (555) 123-4567"
                        className="w-full pl-9 pr-3 py-2.5 bg-background/50 border border-border/50 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500/30 focus:border-emerald-500/50 transition-colors"
                      />
                    </div>
                  </div>
                </div>

                {/* Trust badges */}
                <div className="flex items-center gap-4 py-2">
                  <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                    <ShieldCheck className="w-3.5 h-3.5 text-emerald-500" />
                    <span>Secure payment</span>
                  </div>
                  <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                    <CreditCard className="w-3.5 h-3.5 text-emerald-500" />
                    <span>Powered by Stripe</span>
                  </div>
                </div>
              </div>
            </div>

            {/* Footer with CTA */}
            <div className="sticky bottom-0 bg-card/95 backdrop-blur-sm border-t border-border/50 p-4 pb-[max(1rem,env(safe-area-inset-bottom))]">
              <Button
                onClick={handleSubmit}
                disabled={!isFormValid || isSubmitting}
                className={cn(
                  'w-full h-12 text-base font-semibold gap-2',
                  isFormValid && !isSubmitting && 'shadow-lg shadow-emerald-500/20'
                )}
              >
                {isSubmitting ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    Processing...
                  </>
                ) : (
                  <>
                    Pay {formatPrice(total)}
                    <ArrowRight className="w-4 h-4" />
                  </>
                )}
              </Button>
              <p className="text-[10px] text-center text-muted-foreground mt-2">
                You&apos;ll be redirected to Stripe for secure payment
              </p>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );

  // Render via portal
  if (!mounted) return null;
  return createPortal(sheetContent, document.body);
}

export const CheckoutSheet = memo(CheckoutSheetInner);
export default CheckoutSheet;
