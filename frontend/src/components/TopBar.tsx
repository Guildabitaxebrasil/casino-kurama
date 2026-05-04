import SearchBar from './SearchBar';

interface Props {
  onToggleSidebar: () => void;
}

export default function TopBar({ onToggleSidebar }: Props) {
  return (
    <header className="h-16 bg-kur-bg-card border-b border-kur-border px-4 lg:px-6 flex items-center gap-4 sticky top-0 z-10">
      {/* Mobile hamburger */}
      <button
        onClick={onToggleSidebar}
        className="lg:hidden p-2 rounded-lg text-kur-text-muted hover:text-kur-text hover:bg-kur-bg-hover transition-colors"
        aria-label="Toggle sidebar"
      >
        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
        </svg>
      </button>

      {/* Search */}
      <div className="flex-1 max-w-xl">
        <SearchBar />
      </div>

      {/* Live indicator */}
      <div className="flex items-center gap-2 text-xs text-kur-green">
        <span className="w-2 h-2 rounded-full bg-kur-green animate-pulse" />
        Live
      </div>
    </header>
  );
}
