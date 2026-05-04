import type { Transaction } from '../api/types';
import TransactionRow from './TransactionRow';

interface Props {
  transactions: Transaction[];
  loading?: boolean;
  showBlock?: boolean;
}

export default function TransactionTable({ transactions, loading }: Props) {
  if (loading) {
    return (
      <div className="animate-pulse space-y-3">
        {[1, 2, 3, 4, 5].map(i => (
          <div key={i} className="h-12 bg-kur-bg-card rounded" />
        ))}
      </div>
    );
  }

  if (!transactions.length) {
    return (
      <div className="text-center py-8 text-kur-text-muted">
        <p>Nenhuma transação encontrada</p>
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-kur-border text-kur-text-muted text-xs uppercase tracking-wider">
            <th className="text-left py-3 px-4 font-medium">Hash</th>
            <th className="text-left py-3 px-4 font-medium">Remetente</th>
            <th className="text-left py-3 px-4 font-medium">Destinatário</th>
            <th className="text-right py-3 px-4 font-medium">Valor</th>
            <th className="text-right py-3 px-4 font-medium">Data</th>
          </tr>
        </thead>
        <tbody>
          {transactions.map(tx => (
            <TransactionRow key={tx.transaction_id} tx={tx} />
          ))}
        </tbody>
      </table>
    </div>
  );
}
