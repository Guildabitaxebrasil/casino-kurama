import type { Block } from '../api/types';
import LoadingSpinner from './LoadingSpinner';
import { Link } from 'react-router-dom';

interface Props {
  blocks: Block[];
  loading: boolean;
}

export default function BlockChainVis({ blocks, loading }: Props) {
  if (loading) {
    return (
      <div className="h-32 flex items-center justify-center">
        <LoadingSpinner />
      </div>
    );
  }

  if (!blocks.length) {
    return (
      <div className="h-32 flex items-center justify-center text-kur-text-muted text-sm">
        Nenhum bloco na cadeia
      </div>
    );
  }

  return (
    <div className="overflow-x-auto pb-4">
      <div className="flex items-center gap-0 min-w-max px-2">
        {blocks.map((block, idx) => {
          const isGenesis = block.index === 0;
          const isLatest = idx === blocks.length - 1;
          return (
            <div key={block.hash} className="flex items-center">
              <Link
                to={`/block/${block.index}`}
                className={`
                  w-24 h-24 rounded-lg border-2 flex flex-col items-center justify-center
                  transition-all duration-200 hover:scale-105 hover:shadow-lg
                  ${isGenesis
                    ? 'border-kur-purple bg-kur-purple/5'
                    : isLatest
                      ? 'border-kur-green bg-kur-green/5 shadow-kur-green/20 shadow-lg'
                      : 'border-kur-border bg-kur-bg-card'
                  }
                `}
              >
                <span className={`
                  font-mono font-bold text-sm
                  ${isGenesis ? 'text-kur-purple' : isLatest ? 'text-kur-green' : 'text-kur-accent'}
                `}>
                  #{block.index}
                </span>
                <span className="font-mono text-[10px] text-kur-text-muted mt-1">
                  {block.hash.slice(0, 8)}...
                </span>
                <span className="font-mono text-[9px] text-kur-text-muted/60 mt-0.5">
                  {block.transactions.length} tx
                </span>
              </Link>

              {idx < blocks.length - 1 && (
                <div className="flex items-center mx-2">
                  <div className="w-6 h-[2px] bg-kur-border" />
                  <div className="w-0 h-0 border-t-[5px] border-t-transparent border-b-[5px] border-b-transparent border-l-[8px] border-l-kur-border" />
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
