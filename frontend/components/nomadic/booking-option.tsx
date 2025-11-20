'use client';

import { Plane, Train, Car, Bus } from 'lucide-react';
import { motion } from 'framer-motion';

import type { TravelOption } from '@/lib/mock-data';

interface BookingOptionProps {
  option: TravelOption;
  index: number;
}

const icons = {
  flight: Plane,
  train: Train,
  bus: Bus,
  car: Car,
};

export function BookingOption({ option, index }: BookingOptionProps) {
  const Icon = icons[option.type];

  return (
    <motion.div
      initial={{ opacity: 0, x: -20 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.3, delay: 0.5 + index * 0.1 }}
      className="group flex cursor-pointer items-center justify-between rounded-lg border border-border/50 bg-muted/30 p-3 transition-colors hover:bg-muted/50"
    >
      <div className="flex items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-full bg-white text-primary shadow-sm transition-transform group-hover:scale-110">
          <Icon className="h-5 w-5" />
        </div>
        <div>
          <div className="text-foreground text-sm font-medium">{option.provider}</div>
          <div className="text-muted-foreground text-xs">
            {option.time} • {option.duration}
          </div>
        </div>
      </div>

      <div className="text-right">
        <div className="text-primary text-sm font-bold">{option.price}</div>
        <div className="text-muted-foreground text-[10px] font-medium uppercase tracking-wider">
          {option.type}
        </div>
      </div>
    </motion.div>
  );
}
