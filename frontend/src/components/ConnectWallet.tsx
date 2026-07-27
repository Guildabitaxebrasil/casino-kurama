import { useState, useRef, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useWallet } from '../context/WalletContext';
import { getBalance } from '../api/client';

export default function ConnectWallet() {
  const navigate = useNavigate();
  const { isConnected, currentAddress, savedWallets, connect, createAndConnect, disconnect } = useWallet();
  const [showModal, setShowModal] = useState(false);
  const [balance, setBalance] = useState<number | null>(null);
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [pasteAddress, setPasteAddress] = useState('');
  const [selectedSaved, setSelectedSaved] = useState('');
  const [view, setView] = useState<'menu' | 'create' | 'existing' | 'paste'>('menu');
  const overlayRef = useRef<HTMLDivElement>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);

  // Busca saldo quando conectado
  useEffect(() => {
    if (currentAddress) {
      getBalance(currentAddress)
        .then(r => setBalance(r.balance))
        .catch(() => setBalance(null));
    } else {
      setBalance(null);
    }
  }, [currentAddress]);

  // Fecha dropdown ao clicar fora
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setDropdownOpen(false);
      }
    }
    if (dropdownOpen) {
      document.addEventListener('mousedown', handleClick);
      return () => document.removeEventListener('mousedown', handleClick);
    }
  }, [dropdownOpen]);

  const clearMessages = useCallback(() => {
    setError('');
  }, []);

  const handleCreate = async () => {
    setLoading(true);
    setError('');
    try {
      await createAndConnect();
      setShowModal(false);
      setView('menu');
    } catch (err: any) {
      setError(err.message || 'Erro ao criar carteira');
    } finally {
      setLoading(false);
    }
  };

  const handleConnectSaved = () => {
    if (!selectedSaved) {
      setError('Selecione uma carteira');
      return;
    }
    const w = savedWallets.find(w => w.address === selectedSaved);
    if (!w) {
      setError('Carteira não encontrada');
      return;
    }
    connect(w.address, w.private_key_pem, w.public_key, w.label);
    setShowModal(false);
    setView('menu');
  };

  const handleConnectPaste = () => {
    const addr = pasteAddress.trim();
    if (!addr) {
      setError('Cole um endereço');
      return;
    }
    // Conecta apenas com endereço (modo somente leitura - sem chave privada)
    connect(addr, '', '');
    setShowModal(false);
    setView('menu');
  };

  const handleDisconnect = () => {
    disconnect();
    setDropdownOpen(false);
  };

  const handleOverlayClick = (e: React.MouseEvent) => {
    if (e.target === overlayRef.current) {
      setShowModal(false);
      setView('menu');
      clearMessages();
    }
  };

  // Botão quando desconectado
  if (!isConnected) {
    return (
      <>
        <button
          onClick={() => { setShowModal(true); clearMessages(); }}
          className="flex items-center gap-1.5 px-3 py-2 bg-kur-accent/10 text-kur-accent border border-kur-accent/30 rounded-lg hover:bg-kur-accent/20 transition-colors text-xs font-medium whitespace-nowrap"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
          </svg>
          <span className="hidden md:inline">Conectar</span>
        </button>

        {showModal && (
          <div
            ref={overlayRef}
            onClick={handleOverlayClick}
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4"
          >
            <div className="bg-kur-bg-card border border-kur-border rounded-2xl w-full max-w-md shadow-2xl">
              {/* Header */}
              <div className="flex items-center justify-between px-6 py-4 border-b border-kur-border">
                <h2 className="text-lg font-bold text-kur-text">Conectar Carteira</h2>
                <button
                  onClick={() => { setShowModal(false); setView('menu'); clearMessages(); }}
                  className="p-1.5 rounded-lg text-kur-text-muted hover:text-kur-text hover:bg-kur-bg-hover transition-colors"
                >
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </div>

              {/* Body */}
              <div className="px-6 py-5">
                {error && (
                  <div className="mb-4 bg-kur-red/5 border border-kur-red/20 rounded-lg p-3">
                    <p className="text-xs text-kur-red">❌ {error}</p>
                  </div>
                )}

                {view === 'menu' && (
                  <div className="space-y-3">
                    <p className="text-sm text-kur-text-muted mb-4">
                      Selecione como deseja conectar sua carteira à KuramaChain.
                    </p>

                    <button
                      onClick={() => setView('create')}
                      className="w-full flex items-center gap-3 px-4 py-3 bg-kur-bg border border-kur-border rounded-xl hover:border-kur-accent/30 hover:bg-kur-accent/5 transition-all text-left"
                    >
                      <span className="text-2xl">✨</span>
                      <div>
                        <p className="text-sm font-medium text-kur-text">Criar nova carteira</p>
                        <p className="text-xs text-kur-text-muted">Gera um novo par de chaves na KuramaChain</p>
                      </div>
                    </button>

                    <button
                      onClick={() => setView('existing')}
                      className="w-full flex items-center gap-3 px-4 py-3 bg-kur-bg border border-kur-border rounded-xl hover:border-kur-accent/30 hover:bg-kur-accent/5 transition-all text-left"
                    >
                      <span className="text-2xl">👛</span>
                      <div>
                        <p className="text-sm font-medium text-kur-text">Usar carteira salva</p>
                        <p className="text-xs text-kur-text-muted">
                          {savedWallets.length > 0
                            ? `${savedWallets.length} carteira(s) salva(s) no navegador`
                            : 'Nenhuma carteira salva ainda'}
                        </p>
                      </div>
                    </button>

                    <button
                      onClick={() => setView('paste')}
                      className="w-full flex items-center gap-3 px-4 py-3 bg-kur-bg border border-kur-border rounded-xl hover:border-kur-accent/30 hover:bg-kur-accent/5 transition-all text-left"
                    >
                      <span className="text-2xl">🔗</span>
                      <div>
                        <p className="text-sm font-medium text-kur-text">Colar endereço</p>
                        <p className="text-xs text-kur-text-muted">Conecta com um endereço existente (somente leitura)</p>
                      </div>
                    </button>
                  </div>
                )}

                {view === 'create' && (
                  <div className="space-y-4">
                    <div className="bg-kur-accent/5 border border-kur-accent/20 rounded-xl p-4">
                      <p className="text-sm text-kur-text font-medium mb-2">🔐 Nova Carteira Kurama</p>
                      <p className="text-xs text-kur-text-muted">
                        Será gerado um par de chaves ECDSA (secp256k1). 
                        A chave privada ficará salva apenas no seu navegador.
                        Use-a para assinar transações.
                      </p>
                    </div>
                    <button
                      onClick={handleCreate}
                      disabled={loading}
                      className="w-full px-4 py-3 bg-kur-accent text-white rounded-xl hover:bg-kur-accent/90 transition-colors text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
                    >
                      {loading ? (
                        <>
                          <svg className="animate-spin w-4 h-4" viewBox="0 0 24 24">
                            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                          </svg>
                          Criando...
                        </>
                      ) : (
                        '✨ Gerar Carteira'
                      )}
                    </button>
                    <button
                      onClick={() => setView('menu')}
                      className="w-full text-xs text-kur-text-muted hover:text-kur-text transition-colors"
                    >
                      Voltar
                    </button>
                  </div>
                )}

                {view === 'existing' && (
                  <div className="space-y-4">
                    {savedWallets.length === 0 ? (
                      <div className="bg-kur-bg border border-kur-border rounded-xl p-6 text-center">
                        <p className="text-kur-text-muted text-sm mb-3">Nenhuma carteira salva</p>
                        <button
                          onClick={() => setView('create')}
                          className="text-kur-accent text-sm font-medium hover:underline"
                        >
                          Criar uma agora →
                        </button>
                      </div>
                    ) : (
                      <>
                        <div className="max-h-48 overflow-y-auto space-y-2">
                          {savedWallets.map(w => (
                            <label
                              key={w.address}
                              className={`flex items-center gap-3 px-3 py-2.5 rounded-lg border cursor-pointer transition-all ${
                                selectedSaved === w.address
                                  ? 'border-kur-accent/40 bg-kur-accent/5'
                                  : 'border-kur-border bg-kur-bg hover:border-kur-text-muted/30'
                              }`}
                            >
                              <input
                                type="radio"
                                name="saved-wallet"
                                checked={selectedSaved === w.address}
                                onChange={() => setSelectedSaved(w.address)}
                                className="text-kur-accent focus:ring-kur-accent/30"
                              />
                              <div className="min-w-0 flex-1">
                                <p className="text-xs font-medium text-kur-text truncate">{w.label}</p>
                                <p className="text-[10px] font-mono text-kur-text-muted truncate">{w.address}</p>
                              </div>
                              <span className="text-xs text-kur-text-muted">
                                {new Date(w.created_at).toLocaleDateString()}
                              </span>
                            </label>
                          ))}
                        </div>
                        <button
                          onClick={handleConnectSaved}
                          disabled={!selectedSaved}
                          className="w-full px-4 py-2.5 bg-kur-accent text-white rounded-xl hover:bg-kur-accent/90 transition-colors text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed"
                        >
                          Conectar
                        </button>
                        <button
                          onClick={() => setView('menu')}
                          className="w-full text-xs text-kur-text-muted hover:text-kur-text transition-colors"
                        >
                          Voltar
                        </button>
                      </>
                    )}
                  </div>
                )}

                {view === 'paste' && (
                  <div className="space-y-4">
                    <div>
                      <label className="block text-xs text-kur-text-muted mb-1.5 font-medium">
                        Endereço da carteira
                      </label>
                      <input
                        value={pasteAddress}
                        onChange={e => setPasteAddress(e.target.value)}
                        placeholder="Cole o endereço K... aqui"
                        className="w-full bg-kur-bg border border-kur-border rounded-lg px-3 py-2.5 text-sm font-mono text-kur-text placeholder-kur-text-muted focus:outline-none focus:border-kur-accent"
                      />
                    </div>
                    <p className="text-xs text-kur-text-muted">
                      ⚠ Modo somente leitura — você poderá consultar saldo e transações, 
                      mas precisará da chave privada para enviar transações.
                    </p>
                    <button
                      onClick={handleConnectPaste}
                      disabled={!pasteAddress.trim()}
                      className="w-full px-4 py-2.5 bg-kur-accent text-white rounded-xl hover:bg-kur-accent/90 transition-colors text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      Conectar
                    </button>
                    <button
                      onClick={() => setView('menu')}
                      className="w-full text-xs text-kur-text-muted hover:text-kur-text transition-colors"
                    >
                      Voltar
                    </button>
                  </div>
                )}
              </div>
            </div>
          </div>
        )}
      </>
    );
  }

  // --- CONECTADO: mostra status e dropdown ---
  const shortAddr = currentAddress
    ? `${currentAddress.slice(0, 8)}...${currentAddress.slice(-4)}`
    : '';

  return (
    <div className="relative" ref={dropdownRef}>
      <button
        onClick={() => setDropdownOpen(!dropdownOpen)}
        className="flex items-center gap-2 px-3 py-1.5 bg-kur-green/10 border border-kur-green/30 rounded-lg hover:bg-kur-green/20 transition-colors text-xs font-medium"
      >
        <span className="w-2 h-2 rounded-full bg-kur-green" />
        <span className="hidden sm:inline text-kur-green font-mono text-[11px]">{shortAddr}</span>
        <span className="text-kur-text-muted text-[10px]">
          {balance !== null ? `${balance.toFixed(2)} KUR` : '...'}
        </span>
        <svg className={`w-3 h-3 text-kur-text-muted transition-transform ${dropdownOpen ? 'rotate-180' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {dropdownOpen && (
        <div className="absolute right-0 top-full mt-2 w-72 bg-kur-bg-card border border-kur-border rounded-xl shadow-2xl shadow-black/30 z-50">
          {/* Info */}
          <div className="px-4 py-3 border-b border-kur-border">
            <p className="text-xs text-kur-text-muted mb-1">Conectado como</p>
            <p className="text-xs font-mono text-kur-text break-all">{currentAddress}</p>
            <div className="mt-2 flex items-center gap-2">
              <span className="text-xs text-kur-text-muted">Saldo:</span>
              <span className="text-sm font-bold text-kur-accent">
                {balance !== null ? `${balance.toFixed(2)} KUR` : 'Carregando...'}
              </span>
            </div>
          </div>

          {/* Actions */}
          <div className="p-2 space-y-1">
            <button
              onClick={() => { setDropdownOpen(false); navigate('/wallet?address=' + currentAddress); }}
              className="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-xs text-kur-text hover:bg-kur-bg-hover transition-colors text-left"
            >
              <span>👛</span>
              <span>Ir para Carteira</span>
            </button>
            <button
              onClick={handleDisconnect}
              className="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-xs text-kur-red hover:bg-kur-red/5 transition-colors text-left"
            >
              <span>🔌</span>
              <span>Desconectar</span>
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
