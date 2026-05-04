interface Props { currentPage: number; totalPages: number; onPageChange: (page: number) => void; }
export default function Pagination({ currentPage, totalPages, onPageChange }: Props) {
  if (totalPages <= 1) return null;
  return (
    <div className="flex items-center justify-center gap-2 mt-6">
      <button onClick={() => onPageChange(currentPage - 1)} disabled={currentPage <= 1}
        className="px-3 py-1.5 text-sm rounded-lg bg-kur-bg-card border border-kur-border text-kur-text-muted hover:text-kur-text hover:border-kur-accent disabled:opacity-40 disabled:cursor-not-allowed transition-colors">
        ← Anterior
      </button>
      <span className="text-sm text-kur-text-muted px-3">
        Página {currentPage} de {totalPages}
      </span>
      <button onClick={() => onPageChange(currentPage + 1)} disabled={currentPage >= totalPages}
        className="px-3 py-1.5 text-sm rounded-lg bg-kur-bg-card border border-kur-border text-kur-text-muted hover:text-kur-text hover:border-kur-accent disabled:opacity-40 disabled:cursor-not-allowed transition-colors">
        Próxima →
      </button>
    </div>
  );
}
