import { useState, useEffect, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { search } from '../api/client';
import type { SearchResult } from '../api/types';

export default function SearchBar() {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<SearchResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  const inputRef = useRef<HTMLInputElement>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout>>();

  const doSearch = useCallback(async (q: string) => {
    if (q.length < 2) { setResults(null); setOpen(false); return; }
    setLoading(true);
    try {
      const res = await search(q);
      setResults(res);
      setOpen(true);
    } catch {
      setResults(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => doSearch(query), 300);
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current); };
  }, [query, doSearch]);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node) &&
          inputRef.current && !inputRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  const handleSelect = (path: string) => {
    setOpen(false);
    setQuery('');
    navigate(path);
  };

  const blocks = results?.blocks || [];
  const transactions = results?.transactions || [];
  const addresses = results?.addresses || [];
  const hasResults = blocks.length > 0 || transactions.length > 0 || addresses.length > 0;

  return (
    <div className="relative w-full">
      <div className="relative">
        <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-kur-text-muted" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
        </svg>
        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onFocus={() => { if (query.length >= 2) setOpen(true); }}
          placeholder="Buscar blocos, transações ou endereços..."
          className="w-full pl-10 pr-4 py-2 text-sm bg-kur-bg border border-kur-border rounded-lg text-kur-text placeholder-kur-text-muted focus:outline-none focus:border-kur-accent focus:ring-1 focus:ring-kur-accent/50 transition-colors"
        />
        {loading && (
          <div className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 border-2 border-kur-border border-t-kur-accent rounded-full animate-spin" />
        )}
      </div>

      {open && (
        <div ref={dropdownRef} className="absolute top-full left-0 right-0 mt-2 bg-kur-bg-card border border-kur-border rounded-xl shadow-2xl shadow-black/40 overflow-hidden z-50 max-h-96 overflow-y-auto">
          {!hasResults ? (
            <div className="p-6 text-center text-sm text-kur-text-muted">
              {loading ? 'Buscando...' : query.length < 2 ? 'Digite pelo menos 2 caracteres' : 'Nenhum resultado encontrado'}
            </div>
          ) : (
            <div className="p-2 space-y-2">
              {blocks.length > 0 && (
                <Section title="Blocos">
                  {(blocks as any[]).map((b: any) => (
                    <ResultItem key={b.hash || b.index} onClick={() => handleSelect(`/block/${b.index}`)}>
                      <span className="text-kur-accent">#{b.index}</span>
                      <span className="text-xs font-mono text-kur-text-muted truncate">{b.hash}</span>
                    </ResultItem>
                  ))}
                </Section>
              )}
              {transactions.length > 0 && (
                <Section title="Transações">
                  {(transactions as any[]).map((tx: any) => (
                    <ResultItem key={tx.id || tx.transaction_id} onClick={() => handleSelect(`/block/${tx.block_index}`)}>
                      <span className="text-xs font-mono text-kur-text truncate">{tx.id || tx.transaction_id}</span>
                      <span className="text-xs text-kur-text-muted">{tx.amount} KUR</span>
                    </ResultItem>
                  ))}
                </Section>
              )}
              {addresses.length > 0 && (
                <Section title="Endereços">
                  {addresses.map((addr: string) => (
                    <ResultItem key={addr} onClick={() => handleSelect(`/wallet?address=${addr}`)}>
                      <span className="text-xs font-mono text-kur-green truncate">{addr}</span>
                    </ResultItem>
                  ))}
                </Section>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="px-3 py-1.5 text-xs font-semibold text-kur-text-muted uppercase tracking-wider">{title}</p>
      <div className="space-y-0.5">{children}</div>
    </div>
  );
}

function ResultItem({ onClick, children }: { onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      className="w-full flex items-center gap-3 px-3 py-2 rounded-lg hover:bg-kur-bg-hover transition-colors text-left"
    >
      {children}
    </button>
  );
}
