import { useState } from 'react';
import Sidebar from './Sidebar';
import TopBar from './TopBar';
import type { NetworkType } from './NetworkSelector';

// Network context global (simplificado)
let _globalNetwork: NetworkType = 'kurama';
let _setGlobalNetwork: ((n: NetworkType) => void) | null = null;

export function useNetwork() {
  return {
    network: _globalNetwork,
    setNetwork: _setGlobalNetwork!
  };
}

interface Props {
  children: React.ReactNode;
}

export default function Layout({ children }: Props) {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [network, setNetwork] = useState<NetworkType>('kurama');

  // Sincroniza com o getter global
  _globalNetwork = network;
  _setGlobalNetwork = setNetwork;

  return (
    <div className="flex h-screen overflow-hidden bg-kur-bg">
      <Sidebar isOpen={sidebarOpen} onClose={() => setSidebarOpen(false)} />
      <div className="flex-1 flex flex-col min-w-0">
        <TopBar
          onToggleSidebar={() => setSidebarOpen(!sidebarOpen)}
          network={network}
          onNetworkChange={setNetwork}
        />
        <main className="flex-1 overflow-y-auto p-4 lg:p-6">
          {children}
        </main>
      </div>
    </div>
  );
}
