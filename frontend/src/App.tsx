import { Routes, Route, Navigate } from 'react-router-dom';
import Layout from './components/Layout';
import Dashboard from './pages/Dashboard';
import Explorer from './pages/Explorer';
import BlockDetails from './pages/BlockDetails';
import Transactions from './pages/Transactions';
import Network from './pages/Network';
import Wallet from './pages/Wallet';

export default function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/blocks" element={<Explorer />} />
        <Route path="/block/:id" element={<BlockDetails />} />
        <Route path="/transactions" element={<Transactions />} />
        <Route path="/network" element={<Network />} />
        <Route path="/wallet" element={<Wallet />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Layout>
  );
}
