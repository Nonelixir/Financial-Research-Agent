import type { ComponentProps } from 'react';
import { cn } from '@/lib/utils';
export function Badge({ className, variant: _, ...props }: ComponentProps<'span'> & { variant?: string }) {
  return <span className={cn('inline-flex items-center rounded-md bg-muted px-2 py-1 text-xs',className)} {...props}/>;
}
