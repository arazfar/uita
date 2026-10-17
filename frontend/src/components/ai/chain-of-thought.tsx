/**
 * Adapted from Vercel AI Elements' MIT-licensed ChainOfThought component.
 * https://github.com/vercel/ai-elements/blob/main/packages/elements/src/chain-of-thought.tsx
 * Requested catalog: https://www.shadcn.io/ai/chain-of-thought
 * Uita uses its own theme and one shared Radix root for trigger/content linkage.
 */
import * as Collapsible from '@radix-ui/react-collapsible';
import { BrainIcon, ChevronDownIcon, DotIcon, type LucideIcon } from 'lucide-react';
import type { ComponentProps, ReactNode } from 'react';

export type ChainOfThoughtProps = ComponentProps<typeof Collapsible.Root>;
export function ChainOfThought({ className = '', ...props }: ChainOfThoughtProps) {
  return <Collapsible.Root className={`chain-of-thought ${className}`} {...props} />;
}
export function ChainOfThoughtHeader({ children, className = '', ...props }: ComponentProps<typeof Collapsible.Trigger>) {
  return <Collapsible.Trigger className={`chain-of-thought-header ${className}`} {...props}>
    <BrainIcon size={16} aria-hidden="true" /><span>{children ?? 'Chain of thought'}</span>
    <ChevronDownIcon className="chain-chevron" size={16} aria-hidden="true" />
  </Collapsible.Trigger>;
}
export function ChainOfThoughtContent({ className = '', ...props }: ComponentProps<typeof Collapsible.Content>) {
  return <Collapsible.Content className={`chain-of-thought-content ${className}`} {...props} />;
}
export type ChainOfThoughtStepProps = ComponentProps<'div'> & {
  icon?: LucideIcon;
  label: ReactNode;
  description?: ReactNode;
  status?: 'complete' | 'active' | 'pending';
};
export function ChainOfThoughtStep({ icon: Icon = DotIcon, label, description, status = 'complete', children, className = '', ...props }: ChainOfThoughtStepProps) {
  return <div className={`chain-of-thought-step ${className}`} data-status={status} {...props}>
    <div className="chain-step-marker"><Icon size={16} aria-hidden="true" /></div>
    <div className="chain-step-body"><div className="chain-step-label">{label}</div>
      {description && <div className="chain-step-description">{description}</div>}{children}
    </div>
  </div>;
}
