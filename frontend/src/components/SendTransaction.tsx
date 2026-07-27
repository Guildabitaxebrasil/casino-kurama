import { useState, useEffect, useRef } from 'react';
import { createSignedTransaction } from '../api/client';
import { getStoredWallets, type StoredWallet } from '../utils/walletStorage';

interface Props {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: (msg: string) => void;
  onError: (msg: string) => void;
}

export default function SendTransaction({ isOpen, onClose, onSuccess, onError }: Props) {
  const [wallets, setWallets] = useState<StoredWallet[]>([]);
  const [selectedWallet, setSelectedWallet] = useState<string>('');
  const [receiver, setReceiver] = useState('');
  const [amount, setAmount] = useState('');
  const [fee, setFee] = useState('0.001');
  const [sending, setSending] = useState(false);
  const [customPk, setCustomPk] = useState('');
  const [useCustom, setUseCustom] = useState(false);
  const overlayRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (isOpen) {
      setWallets(getStoredWallets());
      setSelectedWallet('');
      setReceiver('');
      setAmount('');
      setFee('0.001');
      setCustomPk('');
      setUseCustom(false);
      setSending(false);
    }
  }, [isOpen]);

  const handleOverlayClick = (e: React.MouseEvent) => {
    if (e.target === overlayRef.current) onClose();
  };

  const handleSend = async () => {
    const pk = useCustom
      ? customPk.trim()
      : wallets.find(w => w.address === selectedWallet)?.private_key_pem || '';

    if (!pk) {
      onError('Selecione uma carteira ou cole uma chave privada.');
      return;
    }
    if (!receiver.trim()) {
      onError('Digite o endereço do destinatário.');
      return;
    }
    const amt = parseFloat(amount);
    if (isNaN(amt) || amt <= 0) {
      onError('Digite um valor válido.');
      return;
    }
    const feeVal = parseFloat(fee);
    if (isNaN(feeVal) || feeVal < 0.001) {
      onError('Taxa mínima: 0.001 KUR.');
      return;
    }

    setSending(true);
    try {
      const result = await createSignedTransaction({
        private_key_pem: pk,
        receiver: receiver.trim(),
        amount: amt,
        fee: feeVal,
      });
      onSuccess(`✅ ${result.message}`);
      onClose();
    } catch (err: any) {
      const msg = err?.response?.data?.error || err?.message || 'Erro ao criar transação';
      onError(`❌ ${msg}`);
    } finally {
      setSending(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div
      ref={overlayRef}
      onClick={handleOverlayClick}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4"
    >
      <div className="bg-kur-bg-card border border-kur-border rounded-2xl w-full max-w-lg shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-kur-border">
          <div className="flex items-center gap-2">
            <span className="text-lg">💸</span>
            <h2 className="text-lg font-bold text-kur-text">Enviar Transação</h2>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-kur-text-muted hover:text-kur-text hover:bg-kur-bg-hover transition-colors"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Body */}
        <div className="px-6 py-5 space-y-4">
          {/* Wallet selector */}
          <div>
            <label className="block text-sm font-medium text-kur-text mb-1.5">
              Carteira de Origem
            </label>
            {wallets.length > 0 && (
              <div className="flex items-center gap-2 mb-2">
                <button
                  onClick={() => setUseCustom(false)}
                  className={`px-3 py-1 text-xs rounded-lg transition-colors ${
                    !useCustom
                      ? 'bg-kur-accent/20 text-kur-accent border border-kur-accent/30'
                      : 'bg-kur-bg text-kur-text-muted border border-kur-border'
                  }`}
                >
                  Suas carteiras
                </button>
                <button
                  onClick={() => setUseCustom(true)}
                  className={`px-3 py-1 text-xs rounded-lg transition-colors ${
                    useCustom
                      ? 'bg-kur-accent/20 text-kur-accent border border-kur-accent/30'
                      : 'bg-kur-bg text-kur-text-muted border border-kur-border'
                  }`}
                >
                  Chave privada
                </button>
              </div>
            )}

            {useCustom ? (
              <textarea
                value={customPk}
                onChange={e => setCustomPk(e.target.value)}
                placeholder="Cole a chave privada (PEM)..."
                rows={3}
                className="w-full bg-kur-bg border border-kur-border rounded-lg px-3 py-2 text-xs font-mono text-kur-text placeholder-kur-text-muted focus:outline-none focus:border-kur-accent resize-none"
              />
            ) : wallets.length > 0 ? (
              <select
                value={selectedWallet}
                onChange={e => setSelectedWallet(e.target.value)}
                className="w-full bg-kur-bg border border-kur-border rounded-lg px-3 py-2.5 text-sm text-kur-text focus:outline-none focus:border-kur-accent"
              >
                <option value="">Selecione uma carteira...</option>
                {wallets.map(w => (
                  <option key={w.address} value={w.address}>
                    {w.label} — {w.address.slice(0, 16)}...
                  </option>
                ))}
              </select>
            ) : (
              <p className="text-sm text-kur-text-muted">
                Nenhuma carteira salva. Vá em <strong>Wallet</strong> e gere uma, ou use "Chave privada" acima.
              </p>
            )}
          </div>

          {/* Receiver */}
          <div>
            <label className="block text-sm font-medium text-kur-text mb-1.5">
              Destinatário
            </label>
            <input
              value={receiver}
              onChange={e => setReceiver(e.target.value)}
              placeholder="Endereço da carteira de destino..."
              className="w-full bg-kur-bg border border-kur-border rounded-lg px-3 py-2.5 text-sm font-mono text-kur-text placeholder-kur-text-muted focus:outline-none focus:border-kur-accent"
            />
          </div>

          {/* Amount and Fee */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-sm font-medium text-kur-text mb-1.5">
                Quantidade (KUR)
              </label>
              <input
                type="number"
                step="0.001"
                min="0.001"
                value={amount}
                onChange={e => setAmount(e.target.value)}
                placeholder="10.0"
                className="w-full bg-kur-bg border border-kur-border rounded-lg px-3 py-2.5 text-sm font-mono text-kur-text placeholder-kur-text-muted focus:outline-none focus:border-kur-accent"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-kur-text mb-1.5">
                Taxa (KUR)
              </label>
              <input
                type="number"
                step="0.001"
                min="0.001"
                value={fee}
                onChange={e => setFee(e.target.value)}
                className="w-full bg-kur-bg border border-kur-border rounded-lg px-3 py-2.5 text-sm font-mono text-kur-text placeholder-kur-text-muted focus:outline-none focus:border-kur-accent"
              />
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-kur-border">
          <button
            onClick={onClose}
            disabled={sending}
            className="px-4 py-2 text-sm text-kur-text-muted hover:text-kur-text transition-colors"
          >
            Cancelar
          </button>
          <button
            onClick={handleSend}
            disabled={sending}
            className="px-6 py-2.5 bg-kur-accent text-white rounded-lg hover:bg-kur-accent/90 transition-colors text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
          >
            {sending ? (
              <>
                <svg className="animate-spin w-4 h-4" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
                Enviando...
              </>
            ) : (
              'Enviar Transação'
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
