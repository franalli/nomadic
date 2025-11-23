'use client';

import { Compass } from 'lucide-react';
import Link from 'next/link';

import { requestOpenConsentPreferences } from '@/components/nomadic/consent-manager';

export function Footer() {
  return (
    <footer className="border-border bg-secondary/30 border-t py-6 text-sm">
      <div className="container mx-auto px-4">
        <div className="mb-2 flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
          <div className="text-primary flex items-center gap-2">
            <Compass className="h-6 w-6" />
            <span className="font-display text-xl font-bold tracking-tight">Nomadic</span>
          </div>
        </div>

        <div className="border-border/50 text-muted-foreground flex flex-col items-center justify-between gap-2 border-t pt-3 md:flex-row md:items-center">
          <p>© {new Date().getFullYear()} Nomadic Inc. All rights reserved.</p>
          <div className="flex flex-wrap items-center gap-3 md:gap-4">
            <Link
              href="/privacy"
              className="hover:text-foreground transition-colors"
              aria-label="Privacy Policy"
            >
              Privacy
            </Link>
            <Link
              href="/terms"
              className="hover:text-foreground transition-colors"
              aria-label="Terms of Service"
            >
              Terms
            </Link>
            <Link
              href="/cookies"
              className="hover:text-foreground transition-colors"
              aria-label="Cookie Policy"
            >
              Cookies
            </Link>
            <button
              type="button"
              onClick={() => requestOpenConsentPreferences()}
              className="hover:text-foreground transition-colors"
              aria-label="Manage cookie preferences"
            >
              Manage cookies
            </button>
            <Link
              href="/contact"
              className="hover:text-foreground transition-colors"
              aria-label="Contact Nomadic"
            >
              Contact
            </Link>
            <Link
              href="/sitemap"
              className="hover:text-foreground transition-colors"
              aria-label="Sitemap"
            >
              Sitemap
            </Link>
          </div>
        </div>
      </div>
    </footer>
  );
}
