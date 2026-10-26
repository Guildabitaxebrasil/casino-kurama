import { useParams, Link } from 'react-router-dom';
import { useEffect, useState } from 'react';
import TransactionTable from '../components/TransactionTable';
import { getBlockByIdentifier } from '../api/client';

function FieldRow({ label, value, mono = true, link = '' }: { label: string; value: string; mono?: boolean; link?: string }) {
  const content = (
    <div className="flex flex-col sm:flex-row sm:items-center py-3 border-b border-kur-border last:border-0">
      <span className="text-kur-text-muted text-sm font-medium w-40 shrink-0">{label}</span>
      {link ? (
        <Link to={link} className={`${mono ? 'font-mono text-xs' : 'text-sm'} text-kur-accent hover:underline break-all`}>
          {value}
        </Link>
      ) : (
        <span className={`${mono ? 'font-mono text-xs' : 'text-sm'} text-kur-text break-all`}>{value}</span>
      )}
    </div>
  );
  return content;
}

export default function BlockDetails() {
  const { id } = useParams<{ id: string }>();
  const [block, setBlock] = useState<any | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const fetchBlock = () => {
    if (!id) return;
    setLoading(true);
    setError('');
    getBlockByIdentifier(id)
      .then(setBlock)
      .catch((err: any) => setError(err.message || 'Bloco não encontrado'))
      .finally(() => setLoading(false));
  };

  useEffect(() => { fetchBlock(); }, [id]);

  if (loading) {
    return (
      <div>
        <div className="skeleton h-8 w-48 mb-6" />
        <div className="bg-kur-bg-card border border-kur-border rounded-xl p-6">
          {Array.from({ length: 7 }).map((_, i) => (
            <div key={i} className="skeleton h-5 w-full mb-4 last:mb-0" />
          ))}
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col items-center py-20">
        <p className="text-kur-red text-lg mb-2">Bloco não encontrado</p>
        <p className="text-kur-text-muted text-sm mb-6">{error}</p>
        <Link to="/blocks"
          className="px-6 py-2 bg-kur-accent/10 text-kur-accent border border-kur-accent/30 rounded-lg hover:bg-kur-accent/20">
          ← Voltar para Explorer
        </Link>
      </div>
    );
  }

  if (!block) return null;

  const txs = block.transactions || [];
  const prevIndex = block.index > 0 ? block.index - 1 : null;

  return (
    <div>
      <div className="flex items-center gap-4 mb-6">
        <Link to="/blocks" className="text-kur-text-muted hover:text-kur-text transition-colors">
          ← Blocos
        </Link>
        <h1 className="text-2xl font-bold text-kur-text">Bloco #{block.index}</h1>
        {prevIndex !== null && (
          <Link to={`/block/${prevIndex}`}
            className="text-sm text-kur-accent hover:underline ml-auto">
            ← Bloco anterior (#{prevIndex})
          </Link>
        )}
      </div>

      <div className="bg-kur-bg-card border border-kur-border rounded-xl p-6 mb-6">
        <h2 className="text-lg font-semibold text-kur-text mb-4">Informações do Bloco</h2>
        <FieldRow label="Hash do Bloco" value={block.hash} link={`/block/${block.hash}`} />
        <FieldRow label="Previous Hash" value={block.previous_hash} link={block.previous_hash ? `/block/${block.previous_hash}` : ''} />
        <FieldRow label="Merkle Root" value={block.merkle_root || block.merkleRoot || '-'} />
        <FieldRow label="Nonce" value={block.proof !== undefined ? String(block.proof) : '-'} />
        <FieldRow label="Dificuldade" value={String(block.difficulty || '-')} />
        <FieldRow label="Timestamp" value={block.timestamp ? new Date(block.timestamp * 1000).toLocaleString('pt-BR') : '-'} mono={false} />
        <FieldRow label="Transações" value={String(txs.length)} mono={false} />
      </div>

      <div className="bg-kur-bg-card border border-kur-border rounded-xl p-6">
        <h2 className="text-lg font-semibold text-kur-text mb-4">
          Transações ({txs.length})
        </h2>
        {txs.length === 0 ? (
          <p className="text-kur-text-muted text-sm py-6 text-center">
            Este bloco não possui transações (apenas coinbase)
          </p>
        ) : (
          <TransactionTable transactions={txs} />
        )}
      </div>
    </div>
  );
}
