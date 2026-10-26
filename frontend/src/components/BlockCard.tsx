import { Link } from 'react-router-dom';
import type { Block } from '../api/types';

interface Props { block: Block; }
export default function BlockCard({ block }: Props) {
  const txCount = block.transactions.length;
  return (
    <Link to={`/block/${block.index}`} className="block bg-kur-bg-card border border-kur-border rounded-xl p-5 hover:border-kur-accent/40 transition-all hover:shadow-lg hover:shadow-kur-accent/5">
      <div className="flex items-start justify-between">
        <div>
          <div className="flex items-center gap-2 mb-2">
            <span className="text-xs font-bold text-kur-accent bg-kur-accent/10 px-2 py-0.5 rounded">#{block.index}</span>
            <span className="text-xs text-kur-text-muted">{new Date(block.timestamp * 1000).toLocaleString('pt-BR')}</span>
          </div>
          <p className="text-xs font-mono text-kur-text-muted truncate max-w-md">
            Hash: <span className="text-kur-text">{block.hash}</span>
          </p>
          {block.index > 0 && (
            <p className="text-xs font-mono text-kur-text-muted truncate max-w-md mt-1">
              Previous: <span className="text-kur-text-muted">{block.previous_hash}</span>
            </p>
          )}
        </div>
        <div className="text-right flex flex-col items-end gap-1">
          <span className="text-xs bg-kur-green/10 text-kur-green px-2 py-0.5 rounded-full font-medium">{txCount} tx{txCount !== 1 ? 's' : ''}</span>
          <span className="text-xs text-kur-text-muted">nonce: {block.proof}</span>
        </div>
      </div>
    </Link>
  );
}
