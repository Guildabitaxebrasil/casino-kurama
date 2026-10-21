import { useState, useCallback } from 'react';
import SearchBar from './SearchBar';
import SendTransaction from './SendTransaction';
import ConnectWallet from './ConnectWallet';

interface Props {
  onToggleSidebar: () => void;
}

export default function TopBar({ onToggleSidebar }: Props) {
  const [showSendModal, setShowSendModal] = useState(false);
  const [toast, setToast] = useState<{ type: 'success' | 'error'; message: string } | null>(null);

  const showToast = useCallback((type: 'success' | 'error', message: string) => {
    setToast({ type, message });
    setTimeout(() => setToast(null), 5000);
  }, []);

  return (
    <>
      <header className="h-16 bg-kur-bg-card border-b border-kur-border px-4 lg:px-6 flex items-center gap-3 sticky top-0 z-10">
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

        {/* Action Buttons */}
        <div className="flex items-center gap-2">
          {/* Connect Wallet */}
          <ConnectWallet />

          {/* Send Transaction */}
          <button
            onClick={() => setShowSendModal(true)}
            className="hidden sm:flex items-center gap-1.5 px-3 py-2 bg-kur-accent/10 text-kur-accent border border-kur-accent/30 rounded-lg hover:bg-kur-accent/20 transition-colors text-xs font-medium"
          >
            <span>💸</span>
            <span className="hidden md:inline">Enviar</span>
          </button>
        </div>

        {/* Live indicator */}
        <div className="flex items-center gap-2 text-xs text-kur-green">
          <span className="w-2 h-2 rounded-full bg-kur-green animate-pulse" />
          <span className="hidden sm:inline">Live</span>
        </div>
      </header>

      {/* Send Transaction Modal */}
      <SendTransaction
        isOpen={showSendModal}
        onClose={() => setShowSendModal(false)}
        onSuccess={(msg) => showToast('success', msg)}
        onError={(msg) => showToast('error', msg)}
      />

      {/* Toast notification */}
      {toast && (
        <div
          className={`fixed top-20 right-4 z-50 px-4 py-3 rounded-xl shadow-lg border text-sm max-w-md animate-slide-in ${
            toast.type === 'success'
              ? 'bg-kur-green/10 border-kur-green/30 text-kur-green'
              : 'bg-kur-red/10 border-kur-red/30 text-kur-red'
          }`}
        >
          <div className="flex items-center gap-2">
            <span className="text-base">{toast.type === 'success' ? '✅' : '❌'}</span>
            <span>{toast.message}</span>
            <button
              onClick={() => setToast(null)}
              className="ml-auto p-0.5 hover:opacity-70 transition-opacity"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
        </div>
      )}
    </>
  );
}
