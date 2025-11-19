import React from 'react';

export const NomadicLanding: React.FC = () => {
  return (
    <div className="bg-bg text-text font-body min-h-screen">
      {/* Top bar */}
      <header className="border-border bg-surface/80 border-b backdrop-blur">
        <div className="max-w-content mx-auto flex items-center justify-between p-4 md:px-8">
          {/* Logo + brand */}
          <div className="flex items-center gap-3">
            <div className="bg-charcoal text-sand shadow-soft flex size-10 items-center justify-center rounded-full">
              {/* Simple eagle mark */}
              <span className="text-lg font-semibold leading-none">🦅</span>
            </div>
            <span className="font-heading text-text text-xl md:text-2xl">NomadiC</span>
          </div>

          {/* Nav */}
          <nav className="text-text-soft hidden items-center gap-6 text-sm md:flex">
            <button className="hover:text-text transition-colors">Stays</button>
            <button className="hover:text-text transition-colors">Flights</button>
            <button className="hover:text-text transition-colors">Activities</button>
            <button className="hover:text-text transition-colors">Deals</button>
          </nav>

          {/* Auth */}
          <div className="flex items-center gap-3">
            <button className="text-text-soft hover:text-text hidden text-sm md:inline-flex">
              Sign in
            </button>
            <a
              href="#planner"
              className="bg-charcoal text-surface shadow-soft focus-visible:ring-sky focus-visible:ring-offset-bg inline-flex items-center justify-center rounded-full px-4 py-2 text-xs font-medium tracking-wide transition-colors hover:bg-black focus:outline-none focus-visible:ring-2 focus-visible:ring-offset-2"
            >
              Join Nomads
            </a>
          </div>
        </div>
      </header>

      {/* Hero */}
      <main>
        <section className="bg-bg-soft">
          <div className="max-w-content md:py-18 mx-auto flex flex-col gap-10 px-4 py-12 md:flex-row md:items-center md:px-8">
            {/* Copy */}
            <div className="flex-1 space-y-6">
              <h1 className="font-heading text-display text-text">
                Plan trips with
                <span className="text-bronze block">nomad-level precision.</span>
              </h1>
              <p className="text-text-soft max-w-xl text-base">
                NomadiC weaves flights, stays, and experiences into a single, elegant
                itinerary—so your journeys feel as curated as they look.
              </p>
              <div className="text-text-muted flex flex-wrap items-center gap-4 text-xs">
                <span className="bg-surface shadow-soft inline-flex items-center gap-2 rounded-full px-3 py-1">
                  <span className="bg-bronze size-2 rounded-full" />
                  Trusted by frequent flyers
                </span>
                <span className="bg-surface shadow-soft inline-flex items-center gap-2 rounded-full px-3 py-1">
                  <span className="bg-sky size-2 rounded-full" />
                  Built for complex itineraries
                </span>
              </div>
            </div>

            {/* Search panel */}
            <div className="flex-1">
              <div className="border-border bg-surface shadow-card space-y-4 rounded-lg border p-5">
                <h2 className="font-heading text-h3 text-text">Start a new itinerary</h2>

                <form className="space-y-3 text-sm">
                  <div className="space-y-1.5">
                    <label className="text-text-soft block text-xs font-medium">
                      Destination
                    </label>
                    <input
                      type="text"
                      placeholder="City, country, or region"
                      className="border-border bg-surface text-text placeholder:text-text-muted focus-visible:ring-sky focus-visible:ring-offset-surface w-full rounded-md border px-3 py-2 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-offset-2"
                    />
                  </div>

                  <div className="grid gap-3 md:grid-cols-2">
                    <div className="space-y-1.5">
                      <label className="text-text-soft block text-xs font-medium">
                        Check-in
                      </label>
                      <input
                        type="date"
                        className="border-border bg-surface text-text focus-visible:ring-sky focus-visible:ring-offset-surface w-full rounded-md border px-3 py-2 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-offset-2"
                      />
                    </div>
                    <div className="space-y-1.5">
                      <label className="text-text-soft block text-xs font-medium">
                        Check-out
                      </label>
                      <input
                        type="date"
                        className="border-border bg-surface text-text focus-visible:ring-sky focus-visible:ring-offset-surface w-full rounded-md border px-3 py-2 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-offset-2"
                      />
                    </div>
                  </div>

                  <div className="space-y-1.5">
                    <label className="text-text-soft block text-xs font-medium">
                      Guests
                    </label>
                    <select className="border-border bg-surface text-text focus-visible:ring-sky focus-visible:ring-offset-surface w-full rounded-md border px-3 py-2 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-offset-2">
                      <option>1 traveler</option>
                      <option>2 travelers</option>
                      <option>3–5 travelers</option>
                      <option>Group (6+)</option>
                    </select>
                  </div>

                  <button
                    type="submit"
                    className="bg-bronze text-surface shadow-soft focus-visible:ring-sky focus-visible:ring-offset-surface mt-2 inline-flex w-full items-center justify-center rounded-full px-4 py-2.5 text-sm font-medium tracking-wide transition-colors duration-200 hover:bg-[#b48645] focus:outline-none focus-visible:ring-2 focus-visible:ring-offset-2"
                  >
                    Weave my trip
                  </button>

                  <p className="text-text-muted text-[11px]">
                    NomadiC compares flights, stays, and activities from multiple
                    providers—without ads or dark patterns.
                  </p>
                </form>
              </div>
            </div>
          </div>
        </section>

        {/* Destinations */}
        <section className="border-border bg-bg border-t">
          <div className="max-w-content mx-auto px-4 py-12 md:px-8 md:py-16">
            <div className="flex items-end justify-between gap-4">
              <div>
                <h2 className="font-heading text-h2 text-text">Popular routes</h2>
                <p className="text-text-soft mt-2 text-sm">
                  Curated itineraries where NomadiC truly shines.
                </p>
              </div>
              <button className="text-text-soft hover:text-text hidden text-sm font-medium underline-offset-4 hover:underline md:inline-flex">
                See all routes
              </button>
            </div>

            <div className="mt-8 grid gap-6 md:grid-cols-3">
              {[
                {
                  title: 'Alpine Weekends',
                  subtitle: 'Zurich → Alps → Milan',
                },
                {
                  title: 'Desert to Coast',
                  subtitle: 'Marrakesh → Atlas → Essaouira',
                },
                {
                  title: 'Steppe & Skyline',
                  subtitle: 'Ulaanbaatar → Seoul → Tokyo',
                },
              ].map((item) => (
                <article
                  key={item.title}
                  className="border-border bg-surface shadow-card hover:shadow-soft group overflow-hidden rounded-lg border transition-all duration-200 hover:-translate-y-0.5"
                >
                  <div className="from-charcoal/80 via-bronze/60 to-sky/70 h-32 bg-gradient-to-tr" />
                  <div className="space-y-1.5 p-4">
                    <h3 className="font-heading text-text text-lg">{item.title}</h3>
                    <p className="text-text-soft text-xs">{item.subtitle}</p>
                    <p className="text-text-muted pt-2 text-[11px]">
                      Layer flights, trains, and stays into one synced plan. Save as a
                      template or share with friends.
                    </p>
                  </div>
                </article>
              ))}
            </div>
          </div>
        </section>
      </main>

      {/* Footer */}
      <footer className="border-border bg-bg-strong text-text-onDark border-t">
        <div className="max-w-content mx-auto flex flex-col gap-6 px-4 py-8 text-sm md:flex-row md:items-center md:justify-between md:px-8">
          <p className="text-text-onDark/80 text-xs">
            © {new Date().getFullYear()} NomadiC. Crafted for modern nomads.
          </p>
          <div className="text-text-onDark/80 flex flex-wrap gap-4 text-xs">
            <button className="hover:text-sky transition-colors">Privacy</button>
            <button className="hover:text-sky transition-colors">Terms</button>
            <button className="hover:text-sky transition-colors">Support</button>
          </div>
        </div>
      </footer>
    </div>
  );
};

export default NomadicLanding;
