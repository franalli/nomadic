'use client';

import { ArrowRight, Clock, MapPin, Star } from 'lucide-react';
import { motion } from 'framer-motion';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardFooter } from '@/components/ui/card';
import type { Trip } from '@/lib/mock-data';

interface TripCardProps {
  trip: Trip;
  index: number;
}

export function TripCard({ trip, index }: TripCardProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, delay: index * 0.1 }}
    >
      <Card className="group overflow-hidden border-none bg-card/70 shadow-lg transition-shadow duration-300 hover:shadow-xl">
        <div className="relative h-48 overflow-hidden">
          <img
            src={trip.imageUrl}
            alt={trip.destination}
            className="h-full w-full object-cover transition-transform duration-700 group-hover:scale-110"
          />
          <div className="absolute right-3 top-3 flex items-center gap-1 rounded-full bg-black/50 px-2 py-1 text-xs font-medium text-white backdrop-blur-md">
            <Star className="h-3 w-3 fill-accent text-accent" />
            <span>{trip.rating}</span>
          </div>
          <div className="absolute left-3 top-3 flex items-center gap-1 rounded-full bg-black/40 px-2 py-1 text-[11px] text-white">
            <MapPin className="h-3 w-3" />
            <span>{trip.destination}</span>
          </div>
        </div>

        <CardContent className="space-y-3 p-5">
          <div className="flex items-start justify-between">
            <h3 className="text-foreground font-display text-xl font-bold">{trip.destination}</h3>
            <span className="text-primary font-mono font-bold">{trip.price}</span>
          </div>

          <p className="text-muted-foreground text-sm leading-relaxed line-clamp-2">
            {trip.description}
          </p>

          <div className="flex flex-wrap gap-2">
            {trip.tags.map((tag) => (
              <Badge
                key={tag}
                variant="secondary"
                className="border-none bg-secondary/50 text-secondary-foreground font-normal"
              >
                {tag}
              </Badge>
            ))}
          </div>
        </CardContent>

        <CardFooter className="flex items-center justify-between p-5 pt-0 text-sm text-muted-foreground">
          <div className="flex items-center gap-1">
            <Clock className="h-4 w-4" />
            <span>{trip.duration}</span>
          </div>

          <Button variant="ghost" size="sm" className="hover:bg-primary/10 hover:text-primary gap-1 p-0 pr-2">
            Book now
            <ArrowRight className="ml-1 h-4 w-4 transition-transform group-hover:translate-x-1" />
          </Button>
        </CardFooter>
      </Card>
    </motion.div>
  );
}
