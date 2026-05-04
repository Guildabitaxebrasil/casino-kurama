import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Area, AreaChart } from 'recharts';
import type { ChartDataPoint } from '../api/types';
import LoadingSpinner from './LoadingSpinner';

interface Props {
  data: ChartDataPoint[];
  loading: boolean;
}

export default function ChainGrowthChart({ data, loading }: Props) {
  if (loading) {
    return <div className="h-[300px] flex items-center justify-center"><LoadingSpinner /></div>;
  }

  if (!data.length) {
    return (
      <div className="h-[300px] flex items-center justify-center text-kur-text-muted text-sm">
        Nenhum dado disponível ainda
      </div>
    );
  }

  return (
    <div className="h-[300px]">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
          <defs>
            <linearGradient id="txGradient" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#58a6ff" stopOpacity={0.3} />
              <stop offset="95%" stopColor="#58a6ff" stopOpacity={0} />
            </linearGradient>
            <linearGradient id="cumGradient" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#3fb950" stopOpacity={0.3} />
              <stop offset="95%" stopColor="#3fb950" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="#30363d" />
          <XAxis
            dataKey="block"
            stroke="#8b949e"
            tick={{ fill: '#8b949e', fontSize: 12 }}
            tickLine={{ stroke: '#30363d' }}
            label={{ value: 'Bloco', position: 'insideBottom', offset: -5, fill: '#8b949e', fontSize: 12 }}
          />
          <YAxis
            stroke="#8b949e"
            tick={{ fill: '#8b949e', fontSize: 12 }}
            tickLine={{ stroke: '#30363d' }}
          />
          <Tooltip
            contentStyle={{
              backgroundColor: '#161b22',
              border: '1px solid #30363d',
              borderRadius: '8px',
              color: '#e6edf3',
              fontSize: '12px',
            }}
            labelStyle={{ color: '#58a6ff', fontWeight: 'bold' }}
          />
          <Area
            type="monotone"
            dataKey="transactions"
            stroke="#58a6ff"
            fill="url(#txGradient)"
            strokeWidth={2}
            name="Transações"
          />
          <Area
            type="monotone"
            dataKey="cumulativeTx"
            stroke="#3fb950"
            fill="url(#cumGradient)"
            strokeWidth={2}
            name="Acumulado"
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
