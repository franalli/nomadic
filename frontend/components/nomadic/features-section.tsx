'use client';

import { Globe, ShieldCheck, Sparkles, Zap } from 'lucide-react';
import { motion } from 'framer-motion';

const features = [
  {
    icon: Sparkles,
    title: 'AI-Powered Curation',
    description:
      'Stop scrolling through endless reviews. Our AI analyzes millions of data points to find trips that match your specific vibe.',
  },
  {
    icon: Globe,
    title: 'Global Connectivity',
    description:
      'Seamlessly connect flights, trains, and local transport. We handle the complex logistics so you can just go.',
    delay: 0.2,
  },
  {
    icon: ShieldCheck,
    title: 'Verified Stays',
    description:
      'Every accommodation is vetted for digital nomad essentials: fast WiFi, ergonomic workspaces, and safe neighborhoods.',
    delay: 0.4,
  },
  {
    icon: Zap,
    title: 'Instant Booking',
    description:
      'From discovery to confirmed reservation in seconds. No redirects, no hidden fees, just pure travel freedom.',
    delay: 0.6,
  },
];

export function FeaturesSection() {
  return (
    <section className="relative overflow-hidden bg-background py-24">
      <div className="container mx-auto px-4">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.6 }}
          className="mx-auto mb-16 max-w-2xl text-center"
        >
          <h2 className="text-foreground mb-4 text-3xl font-display font-bold md:text-4xl">
            Travel smarter, not harder.
          </h2>
          <p className="text-muted-foreground text-lg">
            The world is big. We make it accessible. Experience the future of travel planning.
          </p>
        </motion.div>

        <div className="grid grid-cols-1 gap-8 md:grid-cols-2 lg:grid-cols-4">
          {features.map((feature, idx) => (
            <motion.div
              key={feature.title}
              initial={{ opacity: 0, y: 20 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{ duration: 0.5, delay: feature.delay ?? idx * 0.1 }}
              className="group rounded-2xl border border-border bg-card/70 p-6 transition-colors hover:border-accent/50"
            >
              <div className="mb-6 flex h-12 w-12 items-center justify-center rounded-xl bg-primary/10 transition-colors group-hover:bg-accent/10">
                <feature.icon className="h-6 w-6 text-primary transition-colors group-hover:text-accent" />
              </div>
              <h3 className="text-foreground mb-3 text-xl font-display font-bold">
                {feature.title}
              </h3>
              <p className="text-muted-foreground leading-relaxed">{feature.description}</p>
            </motion.div>
          ))}
        </div>
      </div>
    </section>
  );
}
