interface Props { title: string; value: string | number; subtitle?: string; icon?: string; accent?: string; }
export default function StatCard({ title, value, subtitle, icon, accent = 'text-kur-accent' }: Props) {
  return (
    <div className="bg-kur-bg-card border border-kur-border rounded-xl p-5 hover:border-kur-accent/30 transition-colors">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-xs font-medium text-kur-text-muted uppercase tracking-wider">{title}</p>
          <p className={`text-2xl font-bold mt-1 font-mono ${accent}`}>{typeof value === 'number' ? value.toLocaleString() : value}</p>
          {subtitle && <p className="text-xs text-kur-text-muted mt-1">{subtitle}</p>}
        </div>
        {icon && <span className="text-2xl opacity-50">{icon}</span>}
      </div>
    </div>
  );
}
