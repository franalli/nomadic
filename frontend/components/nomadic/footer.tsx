'use client';

import { Compass } from 'lucide-react';
import Link from 'next/link';

import { requestOpenConsentPreferences } from '@/components/nomadic/consent-manager';

export function Footer() {
  return (
    <footer className="border-border bg-secondary/30 border-t py-4 text-sm">
      <div className="container mx-auto flex flex-col items-center justify-between gap-4 px-4 md:flex-row">
        <div className="flex flex-col items-center gap-4 md:flex-row md:gap-8">
          <div className="text-primary flex items-center gap-2">
            <Compass className="h-5 w-5" />
            <span className="font-display text-lg font-bold tracking-tight">Nomadic</span>
          </div>

          <div className="text-muted-foreground flex flex-wrap items-center justify-center gap-3 md:gap-4">
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
              Preferences
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
            <span className="text-muted-foreground/50">·</span>
            <Link
              href="/credits"
              className="hover:text-foreground transition-colors"
              aria-label="Image Credits"
            >
              Image Credits
            </Link>
          </div>
        </div>

        <p className="text-muted-foreground text-center md:text-right">
          © {new Date().getFullYear()} Nomadic
        </p>
      </div>
    </footer>
  );
}
