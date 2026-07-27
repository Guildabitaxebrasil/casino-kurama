/**
 * NetworkSelector - Seletor de rede (KuramaChain vs Polygon).
 *
 * Permite ao usuário alternar entre a rede KuramaChain (nativa)
 * e a rede Polygon (ERC-20 USDT).
 *
 * Uso:
 *   <NetworkSelector
 *     network={network}
 *     onNetworkChange={setNetwork}
 *   />
 */
import { useState, useEffect } from 'react';
import { getPolygonInfo, type PolygonNetworkInfo } from '../api/polygon';

export type NetworkType = 'kurama' | 'polygon';

interface Props {
  network: NetworkType;
  onNetworkChange: (network: NetworkType) => void;
}

export default function NetworkSelector({ network, onNetworkChange }: Props) {
  const [polygonInfo, setPolygonInfo] = useState<PolygonNetworkInfo | null>(null);
  const [showDropdown, setShowDropdown] = useState(false);

  // Carrega info da Polygon ao montar
  useEffect(() => {
    getPolygonInfo()
      .then(setPolygonInfo)
      .catch(() => setPolygonInfo(null));
  }, []);

  const networks = [
    {
      id: 'kurama' as NetworkType,
      name: 'KuramaChain',
      symbol: 'KUR',
      icon: '⛓️',
      color: 'text-kur-accent',
      bg: 'bg-kur-accent/10',
      border: 'border-kur-accent/30',
      description: 'Blockchain Kurama nativa',
    },
    {
      id: 'polygon' as NetworkType,
      name: 'Polygon',
      symbol: 'USDT',
      icon: '🟣',
      color: 'text-purple-400',
      bg: 'bg-purple-500/10',
      border: 'border-purple-500/30',
      description: polygonInfo?.connected
        ? `Rede ${polygonInfo.network} • ${polygonInfo.chain_id || '?'}`
        : 'Polygon Network (ERC-20)',
    },
  ];

  const current = networks.find(n => n.id === network) || networks[0];

  return (
    <div className="relative">
      {/* Botão do seletor */}
      <button
        onClick={() => setShowDropdown(!showDropdown)}
        className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium transition-all
          ${current.bg} ${current.color} border ${current.border}
          hover:opacity-80`}
      >
        <span>{current.icon}</span>
        <span>{current.name}</span>
        <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${current.bg} ${current.color}`}>
          {current.symbol}
        </span>
        <svg className={`w-3 h-3 transition-transform ${showDropdown ? 'rotate-180' : ''}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {/* Dropdown */}
      {showDropdown && (
        <>
          {/* Backdrop */}
          <div
            className="fixed inset-0 z-40"
            onClick={() => setShowDropdown(false)}
          />

          {/* Menu */}
          <div className="absolute right-0 top-full mt-2 z-50 w-72 bg-kur-bg-card border border-kur-border rounded-xl shadow-2xl overflow-hidden">
            <div className="p-3 border-b border-kur-border">
              <p className="text-[10px] text-kur-text-muted uppercase tracking-wider font-medium">Selecionar Rede</p>
            </div>

            <div className="p-2">
              {networks.map((net) => (
                <button
                  key={net.id}
                  onClick={() => {
                    onNetworkChange(net.id);
                    setShowDropdown(false);
                  }}
                  className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-left transition-colors
                    ${network === net.id
                      ? `${net.bg} border ${net.border}`
                      : 'hover:bg-kur-bg-hover border border-transparent'
                    }`}
                >
                  <span className="text-lg">{net.icon}</span>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className={`text-sm font-medium ${network === net.id ? net.color : 'text-kur-text'}`}>
                        {net.name}
                      </span>
                      <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold
                        ${net.bg} ${net.color}`}>
                        {net.symbol}
                      </span>
                    </div>
                    <p className="text-[10px] text-kur-text-muted truncate mt-0.5">
                      {net.description}
                    </p>
                  </div>
                  {network === net.id && (
                    <svg className={`w-4 h-4 ${net.color}`} fill="currentColor" viewBox="0 0 20 20">
                      <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                    </svg>
                  )}
                </button>
              ))}
            </div>

            {/* Info da Polygon */}
            {polygonInfo && (
              <div className="p-3 border-t border-kur-border bg-kur-bg/50">
                <div className="flex items-center gap-2 text-[10px] text-kur-text-muted">
                  <span className={`w-2 h-2 rounded-full ${polygonInfo.connected ? 'bg-green-400' : 'bg-red-400'}`} />
                  <span>
                    Polygon {polygonInfo.network} • Chain {polygonInfo.chain_id || '?'}
                  </span>
                </div>
                {polygonInfo.block_number && (
                  <p className="text-[10px] text-kur-text-muted mt-1 font-mono">
                    Bloco: #{polygonInfo.block_number.toLocaleString()}
                  </p>
                )}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
