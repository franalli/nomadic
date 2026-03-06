'use client';

import { UserCircle2 } from 'lucide-react';
import { useEffect, useState } from 'react';

import { cn } from '@/lib/utils';

interface UserAvatarProps {
  src?: string | null;
  alt: string;
  imageClassName: string;
  iconClassName?: string;
}

export function UserAvatar({
  src,
  alt,
  imageClassName,
  iconClassName,
}: UserAvatarProps) {
  const [imageFailed, setImageFailed] = useState(false);

  useEffect(() => {
    setImageFailed(false);
  }, [src]);

  if (src && !imageFailed) {
    return (
      <img
        src={src}
        alt={alt}
        className={imageClassName}
        onError={() => setImageFailed(true)}
      />
    );
  }

  return (
    <UserCircle2
      className={cn('text-muted-foreground', iconClassName)}
      aria-hidden="true"
    />
  );
}
