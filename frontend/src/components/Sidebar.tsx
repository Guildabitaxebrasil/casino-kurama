import { NavLink } from 'react-router-dom';

const navItems = [
  { to: '/', label: 'Dashboard', icon: '📊' },
  { to: '/blocks', label: 'Explorer', icon: '🔗' },
  { to: '/transactions', label: 'Transactions', icon: '💳' },
  { to: '/network', label: 'Network', icon: '🌐' },
  { to: '/wallet', label: 'Wallet', icon: '👛' },
];

interface Props {
  isOpen: boolean;
  onClose: () => void;
}

export default function Sidebar({ isOpen, onClose }: Props) {
  return (
    <>
      {/* Mobile backdrop */}
      {isOpen && (
        <div className="fixed inset-0 bg-black/50 z-20 lg:hidden" onClick={onClose} />
      )}

      {/* Sidebar */}
      <aside className={`
        fixed top-0 left-0 z-30 h-screen w-64
        bg-kur-bg-card border-r border-kur-border
        transform transition-transform duration-200 ease-in-out
        lg:translate-x-0 lg:static lg:z-auto
        ${isOpen ? 'translate-x-0' : '-translate-x-full'}
      `}>
        {/* Logo */}
        <div className="flex items-center gap-3 px-6 h-16 border-b border-kur-border">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-kur-accent to-kur-purple flex items-center justify-center text-white font-bold text-sm">
            K
          </div>
          <div>
            <h1 className="text-base font-bold text-kur-text tracking-tight">Kurama Chain</h1>
            <p className="text-[10px] text-kur-text-muted -mt-0.5">Blockchain Explorer</p>
          </div>
        </div>

        {/* Navigation */}
        <nav className="p-4 space-y-1">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === '/'}
              onClick={onClose}
              className={({ isActive }) =>
                `flex items-center gap-3 px-4 py-2.5 rounded-lg text-sm font-medium transition-colors ${
                  isActive
                    ? 'bg-kur-accent/10 text-kur-accent border border-kur-accent/20'
                    : 'text-kur-text-muted hover:text-kur-text hover:bg-kur-bg-hover border border-transparent'
                }`
              }
            >
              <span className="text-base">{item.icon}</span>
              {item.label}
            </NavLink>
          ))}
        </nav>

        {/* Version */}
        <div className="absolute bottom-0 left-0 right-0 p-4 border-t border-kur-border">
          <p className="text-xs text-kur-text-muted text-center">v1.0.0 — Kurama Chain</p>
        </div>
      </aside>
    </>
  );
}
