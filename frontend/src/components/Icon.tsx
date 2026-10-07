/**
 * The desk's icon set — drawn here rather than pulled from a font or an
 * emoji, so every mark shares one grid and one stroke weight.
 *
 * 24×24 box, 1.6 stroke, round caps and joins. The five agent marks are the
 * important ones: each agent is identified by its mark as well as its colour,
 * so the feed is still readable to someone who cannot tell the hues apart.
 */

export type IconName =
  | 'boss'
  | 'inventory'
  | 'accounting'
  | 'facilities'
  | 'customer_service'
  | 'tool'
  | 'arrow'
  | 'check'
  | 'cross'
  | 'clock'
  | 'stamp'
  | 'play'
  | 'reset'
  | 'alert'
  | 'ledger'
  | 'quill'

const paths: Record<IconName, React.ReactNode> = {
  // A desk bell: the boss is who you ring.
  boss: (
    <>
      <path d="M4 17h16" />
      <path d="M6 17a6 6 0 0 1 12 0" />
      <path d="M12 5v2" />
      <circle cx="12" cy="4" r="1.1" />
    </>
  ),
  // A stock carton.
  inventory: (
    <>
      <path d="M3.5 7.5 12 4l8.5 3.5v9L12 20l-8.5-3.5z" />
      <path d="M3.5 7.5 12 11l8.5-3.5" />
      <path d="M12 11v9" />
    </>
  ),
  // A balance scale.
  accounting: (
    <>
      <path d="M12 4v16" />
      <path d="M7 20h10" />
      <path d="M5 8h14" />
      <path d="M5 8 2.8 13a2.6 2.6 0 0 0 4.4 0z" />
      <path d="M19 8l2.2 5a2.6 2.6 0 0 1-4.4 0z" />
    </>
  ),
  // The shopfront.
  facilities: (
    <>
      <path d="M4 9.5V20h16V9.5" />
      <path d="M3 9.5 5 4h14l2 5.5a3 3 0 0 1-6 0 3 3 0 0 1-6 0 3 3 0 0 1-6 0z" />
      <path d="M10 20v-5h4v5" />
    </>
  ),
  // A written reply.
  customer_service: (
    <>
      <path d="M4 5.5h16v10H9l-5 4z" />
      <path d="M8 9.5h8" />
      <path d="M8 12.5h5" />
    </>
  ),
  tool: (
    <>
      <circle cx="12" cy="12" r="2.6" />
      <path d="M12 4.2v2.1M12 17.7v2.1M19.8 12h-2.1M6.3 12H4.2M17.5 6.5l-1.5 1.5M8 16l-1.5 1.5M17.5 17.5 16 16M8 8 6.5 6.5" />
    </>
  ),
  arrow: (
    <>
      <path d="M4 12h15" />
      <path d="M13.5 6.5 20 12l-6.5 5.5" />
    </>
  ),
  check: <path d="M4.5 12.5 9.5 17.5 19.5 6.5" />,
  cross: (
    <>
      <path d="M6 6l12 12" />
      <path d="M18 6 6 18" />
    </>
  ),
  clock: (
    <>
      <circle cx="12" cy="12" r="8" />
      <path d="M12 7.5V12l3 2" />
    </>
  ),
  // A rubber stamp, for a resolved ticket.
  stamp: (
    <>
      <path d="M5 20h14" />
      <path d="M6.5 16.5h11v-2h-11z" />
      <path d="M9.5 14.5V11a2.5 2.5 0 0 1 5 0v3.5" />
      <path d="M12 8.5V4" />
    </>
  ),
  play: <path d="M8 5.5 18.5 12 8 18.5z" />,
  reset: (
    <>
      <path d="M4 11a8 8 0 1 1 2.2 6.2" />
      <path d="M4 5.5V11h5.5" />
    </>
  ),
  alert: (
    <>
      <path d="M12 4.5 21 19.5H3z" />
      <path d="M12 10v4" />
      <circle cx="12" cy="16.8" r=".9" fill="currentColor" stroke="none" />
    </>
  ),
  ledger: (
    <>
      <path d="M5 4h12a2 2 0 0 1 2 2v14H7a2 2 0 0 1-2-2z" />
      <path d="M5 16h14" />
      <path d="M9 8h6M9 11.5h6" />
    </>
  ),
  quill: (
    <>
      <path d="M4 20c6-1 10-4 13-9 1.5-2.5 2-5 2-5s-3 .3-5.5 1.6C9 9.5 6.5 13 5.5 18" />
      <path d="M4 20l5-5" />
    </>
  ),
}

interface Props {
  name: IconName
  size?: number
  strokeWidth?: number
  className?: string
}

export default function Icon({
  name,
  size = 18,
  strokeWidth = 1.6,
  className,
}: Props) {
  return (
    <svg
      className={className}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {paths[name]}
    </svg>
  )
}
