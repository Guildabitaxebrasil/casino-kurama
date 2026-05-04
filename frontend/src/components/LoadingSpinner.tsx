interface Props { size?: 'sm' | 'md' | 'lg'; text?: string; }
export default function LoadingSpinner({ size = 'md', text = 'Carregando...' }: Props) {
  const sizeMap = { sm: 'h-4 w-4', md: 'h-8 w-8', lg: 'h-12 w-12' };
  return (
    <div className="flex flex-col items-center justify-center py-12">
      <div className={`${sizeMap[size]} animate-spin rounded-full border-2 border-kur-border border-t-kur-accent`} />
      <p className="mt-3 text-sm text-kur-text-muted">{text}</p>
    </div>
  );
}
