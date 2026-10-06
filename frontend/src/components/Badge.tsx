import type { RiskLevel } from '../api'

/** Risk level as a status badge: a coloured dot plus the label, never colour alone. */
export function RiskBadge({ level }: { level: RiskLevel | null | undefined }) {
  if (!level) return <span className="badge low"><i />Not scored</span>
  return (
    <span className={`badge ${level.toLowerCase()}`}>
      <i />
      {level}
    </span>
  )
}

export function SeverityBadge({ severity }: { severity: string }) {
  return (
    <span className={`badge sev-${severity}`}>
      <i />
      {severity.charAt(0).toUpperCase() + severity.slice(1)}
    </span>
  )
}
