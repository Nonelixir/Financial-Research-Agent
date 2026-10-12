import { Slot } from '@radix-ui/react-slot';
import type { ComponentProps } from 'react';
import { cn } from '@/lib/utils';
export function Button({ asChild, className, size = 'default', variant = 'default', ...props }:
  ComponentProps<'button'> & { asChild?: boolean; size?: string; variant?: string }) {
  const Component = asChild ? Slot : 'button';
  return <Component className={cn('inline-flex items-center justify-center gap-2 rounded-md text-sm transition-colors disabled:opacity-40',
    size === 'sm' ? 'h-8 px-3' : 'h-9 px-4', variant === 'ghost' ? 'hover:bg-muted' : 'bg-primary text-primary-foreground', className)} {...props}/>;
}
