import { useEffect, useState } from 'react';

interface NextBlockCountdownProps {
  /** Timestamp (segundos) em que o próximo bloco pode ser minerado. */
  nextBlockAt?: number | null;
  /** Alvo de segundos por bloco (default: 600 = 10 min). */
  targetBlockTime?: number;
}

function format(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds));
  const minutes = Math.floor(total / 60);
  const rest = total % 60;
  return `${String(minutes).padStart(2, '0')}:${String(rest).padStart(2, '0')}`;
}

/**
 * Contagem para o próximo bloco, no ritmo de 10 minutos do Bitcoin.
 *
 * O alvo vem de `/stats` (next_block_at / target_block_time) e é atualizado
 * via SSE quando um bloco novo é minerado.
 */
export default function NextBlockCountdown({
  nextBlockAt,
  targetBlockTime,
}: NextBlockCountdownProps) {
  const [now, setNow] = useState(() => Date.now() / 1000);

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => clearInterval(id);
  }, []);

  if (!nextBlockAt) return null;

  const total = targetBlockTime && targetBlockTime > 0 ? targetBlockTime : 600;
  const remaining = Math.max(0, nextBlockAt - now);
  const ready = remaining <= 0;
  const progress = Math.min(100, Math.max(0, ((total - remaining) / total) * 100));

  return (
    <div className="w-full sm:w-52" title={`Alvo: ${format(total)} por bloco`}>
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-[10px] sm:text-xs text-kur-text-muted">Próximo bloco</span>
        <span
          className={`text-xs sm:text-sm font-mono font-semibold ${
            ready ? 'text-kur-green' : 'text-kur-accent'
          }`}
        >
          {ready ? 'disponível' : format(remaining)}
        </span>
      </div>
      <div className="w-full bg-kur-bg-hover rounded-full h-1.5">
        <div
          className={`h-full rounded-full transition-all duration-500 ${
            ready ? 'bg-kur-green' : 'bg-kur-accent'
          }`}
          style={{ width: `${progress}%` }}
        />
      </div>
      <span className="block mt-1 text-[10px] text-kur-text-muted">
        alvo de {Math.round(total / 60)} min por bloco
      </span>
    </div>
  );
}
