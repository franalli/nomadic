import { Compass } from 'lucide-react';

export function Footer() {
  return (
    <footer className="border-border bg-secondary/30 border-t py-12 text-sm">
      <div className="container mx-auto px-4">
        <div className="mb-12 grid grid-cols-1 gap-8 md:grid-cols-4">
          <div className="col-span-1 md:col-span-1">
            <div className="mb-4 flex items-center gap-2 text-primary">
              <Compass className="h-6 w-6" />
              <span className="font-display text-xl font-bold tracking-tight">Nomadic</span>
            </div>
            <p className="text-muted-foreground leading-relaxed">
              Exploring the world, one AI-curated trip at a time. Built for the modern wanderer.
            </p>
          </div>

          <div>
            <h4 className="text-foreground mb-4 font-bold">Product</h4>
            <ul className="text-muted-foreground space-y-2">
              <li className="hover:text-accent cursor-pointer transition-colors">Destinations</li>
              <li className="hover:text-accent cursor-pointer transition-colors">Trip Planner</li>
              <li className="hover:text-accent cursor-pointer transition-colors">Flights</li>
              <li className="hover:text-accent cursor-pointer transition-colors">Stays</li>
            </ul>
          </div>

          <div>
            <h4 className="text-foreground mb-4 font-bold">Company</h4>
            <ul className="text-muted-foreground space-y-2">
              <li className="hover:text-accent cursor-pointer transition-colors">About Us</li>
              <li className="hover:text-accent cursor-pointer transition-colors">Careers</li>
              <li className="hover:text-accent cursor-pointer transition-colors">Blog</li>
              <li className="hover:text-accent cursor-pointer transition-colors">Press</li>
            </ul>
          </div>

          <div>
            <h4 className="text-foreground mb-4 font-bold">Connect</h4>
            <ul className="text-muted-foreground space-y-2">
              <li className="hover:text-accent cursor-pointer transition-colors">Twitter</li>
              <li className="hover:text-accent cursor-pointer transition-colors">Instagram</li>
              <li className="hover:text-accent cursor-pointer transition-colors">LinkedIn</li>
              <li className="hover:text-accent cursor-pointer transition-colors">Discord</li>
            </ul>
          </div>
        </div>

        <div className="border-border/50 text-muted-foreground flex flex-col items-center justify-between gap-4 border-t pt-8 md:flex-row">
          <p>© {new Date().getFullYear()} Nomadic Inc. All rights reserved.</p>
          <div className="flex gap-6">
            <span className="hover:text-foreground cursor-pointer transition-colors">Privacy</span>
            <span className="hover:text-foreground cursor-pointer transition-colors">Terms</span>
            <span className="hover:text-foreground cursor-pointer transition-colors">Sitemap</span>
          </div>
        </div>
      </div>
    </footer>
  );
}
