export type Trip = {
  id: string;
  destination: string;
  description: string;
  imageUrl: string;
  price: string;
  duration: string;
  tags: string[];
  rating: number;
};

export type TravelOption = {
  id: string;
  type: 'flight' | 'train' | 'bus' | 'car';
  provider: string;
  time: string;
  price: string;
  duration: string;
};

export const MOCK_TRIPS: Trip[] = [
  {
    id: '1',
    destination: 'Kyoto, Japan',
    description:
      'Experience the ancient temples and traditional tea houses in the cultural heart of Japan. Perfect for digital nomads seeking tranquility.',
    imageUrl:
      'https://images.unsplash.com/photo-1493976040374-85c8e12f0c0e?q=80&w=2070&auto=format&fit=crop',
    price: '$1,200',
    duration: '7 days',
    tags: ['Culture', 'History', 'Zen'],
    rating: 4.8,
  },
  {
    id: '2',
    destination: 'Reykjavik, Iceland',
    description:
      'Hunt for the Northern Lights and soak in geothermal lagoons. A rugged adventure for the modern explorer.',
    imageUrl:
      'https://images.unsplash.com/photo-1476610182048-b716b8518aae?q=80&w=2127&auto=format&fit=crop',
    price: '$1,800',
    duration: '5 days',
    tags: ['Nature', 'Adventure', 'Cold'],
    rating: 4.9,
  },
  {
    id: '3',
    destination: 'Tulum, Mexico',
    description:
      'Work from beachside cafes and explore ancient Mayan ruins. The ultimate balance of productivity and paradise.',
    imageUrl:
      'https://images.unsplash.com/photo-1506197603052-3cc9c3a201bd?q=80&w=2070&auto=format&fit=crop',
    price: '$950',
    duration: '6 days',
    tags: ['Beach', 'Relaxation', 'Ruins'],
    rating: 4.7,
  },
];

export const MOCK_TRAVEL_OPTIONS: TravelOption[] = [
  { id: 't1', type: 'flight', provider: 'Nomadic Air', time: '10:00 AM', price: '$450', duration: '12h' },
  { id: 't2', type: 'flight', provider: 'Skyline', time: '2:00 PM', price: '$380', duration: '14h' },
  { id: 't3', type: 'train', provider: 'RailConnect', time: '09:30 AM', price: '$120', duration: '4h (Local)' },
];
