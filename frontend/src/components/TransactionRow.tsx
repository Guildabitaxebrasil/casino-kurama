import type { Transaction } from '../api/types';

interface Props {
  tx: Transaction;
  showBlock?: boolean;
}

export default function TransactionRow({ tx }: Props) {
  const isCoinbase = tx.sender === '0';

  return (
    <tr className="border-b border-kur-border hover:bg-kur-bg-hover/50 transition-colors">
      <td className="py-3 px-4">
        <p className="font-mono text-xs text-kur-accent truncate max-w-[120px]" title={tx.transaction_id}>
          {tx.transaction_id.slice(0, 16)}...
        </p>
      </td>
      <td className="py-3 px-4">
        {isCoinbase ? (
          <span className="text-xs bg-kur-green/10 text-kur-green px-2 py-0.5 rounded">Coinbase</span>
        ) : (
          <p className="font-mono text-xs text-kur-text truncate max-w-[120px]" title={tx.sender}>
            {tx.sender.slice(0, 16)}...
          </p>
        )}
      </td>
      <td className="py-3 px-4">
        <p className="font-mono text-xs text-kur-text truncate max-w-[120px]" title={tx.receiver}>
          {tx.receiver.slice(0, 16)}...
        </p>
      </td>
      <td className="py-3 px-4 text-right">
        <span className="text-sm font-mono font-medium text-kur-text">{tx.amount.toFixed(2)}</span>
      </td>
      <td className="py-3 px-4 text-right">
        <span className="text-xs text-kur-text-muted">{new Date(tx.timestamp * 1000).toLocaleString('pt-BR')}</span>
      </td>
    </tr>
  );
}
