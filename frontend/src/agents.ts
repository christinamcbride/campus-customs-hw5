/** One identity per agent: a colour of ink, a drawn mark, and a short title. */

import type { IconName } from './components/Icon'
import type { RoleName } from './types'

export interface AgentLook {
  title: string
  icon: IconName
  /** CSS custom properties, applied inline so a mark carries its own ink. */
  vars: React.CSSProperties
}

const ROLES: RoleName[] = [
  'boss',
  'inventory',
  'accounting',
  'facilities',
  'customer_service',
]

export const AGENT_TITLES: Record<RoleName, string> = {
  boss: 'Boss',
  inventory: 'Inventory',
  accounting: 'Accounting',
  facilities: 'Facilities',
  customer_service: 'Customer Service',
}

export function isRole(name: string | null | undefined): name is RoleName {
  return !!name && (ROLES as string[]).includes(name)
}

export function look(name: string | null | undefined): AgentLook {
  if (!isRole(name)) {
    return {
      title: 'Desk',
      icon: 'ledger',
      vars: { '--hue': 'var(--ink-2)', '--tint': 'var(--paper-sunk)' } as React.CSSProperties,
    }
  }
  return {
    title: AGENT_TITLES[name],
    icon: name,
    vars: {
      '--hue': `var(--${name})`,
      '--tint': `var(--${name}-tint)`,
    } as React.CSSProperties,
  }
}
