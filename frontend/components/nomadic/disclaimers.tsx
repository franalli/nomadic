import Link from 'next/link';

/**
 * Reusable disclaimer components for booking flow compliance.
 * Used to meet Expedia Rapid API and Booking.com partner requirements.
 */

export function SupplierDisclaimer() {
  return (
    <p className="text-xs text-muted-foreground">
      Prices and availability from partners.
    </p>
  );
}

export function PricingDisclaimer() {
  return (
    <p className="text-xs text-muted-foreground">
      Final price, taxes, and fees determined by supplier at checkout.
    </p>
  );
}

export function EstimatedTotalDisclaimer() {
  return (
    <p className="text-xs text-muted-foreground">
      Estimated total. Final price includes taxes and fees applied by the supplier.
    </p>
  );
}

type SupplierTermsLinkProps = {
  provider: 'expedia' | 'booking';
  className?: string;
};

const SUPPLIER_TERMS: Record<'expedia' | 'booking', { name: string; url: string }> = {
  expedia: {
    name: 'Expedia Group',
    url: 'https://www.expedia.com/lp/lg-legal',
  },
  booking: {
    name: 'Booking.com',
    url: 'https://www.booking.com/content/terms.html',
  },
};

export function SupplierTermsLink({ provider, className }: SupplierTermsLinkProps) {
  const { name, url } = SUPPLIER_TERMS[provider];
  return (
    <a
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      className={className ?? 'text-primary underline text-xs'}
    >
      {name} Terms and Conditions
    </a>
  );
}

export function BookingDisclaimer() {
  return (
    <div className="rounded-lg border border-border/50 bg-muted/30 p-3 text-xs text-muted-foreground space-y-2">
      <p>
        <strong>Important:</strong> By proceeding, you acknowledge that:
      </p>
      <ul className="list-disc pl-4 space-y-1">
        <li>Payment will be collected by the booking supplier, not Nomadic</li>
        <li>Final price, taxes, and fees are determined at checkout</li>
        <li>Supplier terms and cancellation policies apply</li>
      </ul>
      <p>
        View our{' '}
        <Link href="/terms" className="text-primary underline">
          Terms of Service
        </Link>{' '}
        for more details.
      </p>
    </div>
  );
}

/**
 * Expedia-specific booking disclosure component.
 * Shows supplier attribution, payment collector, and terms link.
 * Required for Expedia Rapid API compliance.
 */
export function BookingDisclosure() {
  return (
    <div className="rounded-lg border border-border/50 bg-muted/30 p-4 text-sm text-muted-foreground space-y-3">
      <div className="space-y-1">
        <p>
          <strong className="text-foreground">Booking provided by:</strong> Expedia Group
        </p>
        <p>
          <strong className="text-foreground">Payment collected by:</strong> Expedia Group or the property
        </p>
      </div>
      <p className="text-xs">
        Final price, taxes, and fees are determined by Expedia at checkout.
        Cancellation policies vary by rate.
      </p>
      <p>
        <a
          href="https://www.expedia.com/lp/lg-legal"
          target="_blank"
          rel="noopener noreferrer"
          className="text-primary underline hover:text-primary/80"
        >
          Expedia Group Terms and Conditions
        </a>
      </p>
    </div>
  );
}
