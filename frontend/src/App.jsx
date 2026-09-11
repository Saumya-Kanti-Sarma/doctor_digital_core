import { useState } from 'react';
import './index.css';
import Dashboard from './pages/Dashboard/Dashboard';
import RecoverySetup from './pages/RecoverySetup/RecoverySetup';
import DriveExplorer from './pages/DriveExplorer/DriveExplorer';

export default function App() {
  const [page, setPage] = useState('dashboard');
  const [activeDrive, setActiveDrive] = useState(null);

  function handleOpen(drive) {
    setActiveDrive(drive);
    setPage('explorer');
  }

  function handleRecover(drive) {
    setActiveDrive(drive);
    setPage('recovery');
  }

  function handleBackToDashboard() {
    setPage('dashboard');
  }

  if (page === 'explorer') {
    return <DriveExplorer drive={activeDrive} onBack={handleBackToDashboard} />;
  }

  if (page === 'recovery') {
    return (
      <RecoverySetup
        drive={activeDrive}
        onCancel={handleBackToDashboard}
        onStartRecovery={handleBackToDashboard}
      />
    );
  }

  return <Dashboard onOpen={handleOpen} onRecover={handleRecover} />;
}
