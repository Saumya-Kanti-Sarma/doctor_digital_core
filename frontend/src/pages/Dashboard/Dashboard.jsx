import { useState } from 'react';
import Sidebar from '../../components/Sidebar/Sidebar';
import USBTable from '../../components/USBTable/USBTable';
import './Dashboard.css';

const DEMO_DRIVES = [
  { model: 'SanDisk Ultra 3.0',    serial: 'SDU3-4A2F-8C1E', size: '64 GB',  status: 'Online'   },
  { model: 'Kingston DataTraveler', serial: 'KDT2-9B3D-5F7A', size: '32 GB',  status: 'Infected' },
  { model: 'Samsung BAR Plus',      serial: 'SBP1-7E6C-2D4B', size: '128 GB', status: 'Online'   },
  { model: 'Corsair Flash Voyager', serial: 'CFV5-1A9F-3E8D', size: '16 GB',  status: 'Unknown'  },
  { model: 'Lexar JumpDrive S47',   serial: 'LJS4-6C0B-9A2E', size: '256 GB', status: 'Scanning' },
];

export default function Dashboard({ onOpen, onRecover }) {
  const [drives, setDrives] = useState([]);
  const [scanning, setScanning] = useState(false);
  const [selectedDrive, setSelectedDrive] = useState(null);

  function handleScan() {
    if (scanning) return;
    setDrives([]);
    setSelectedDrive(null);
    setScanning(true);
    // Simulate a scan — replace with real API call
    setTimeout(() => {
      setScanning(false);
      setDrives(DEMO_DRIVES);
      setSelectedDrive(DEMO_DRIVES[0]); // auto-select first drive
    }, 2000);
  }

  return (
    <div className="dashboard-wrapper">
      <div className="dashboard">
        <Sidebar onScan={handleScan} scanning={scanning} />
        <USBTable
          drives={drives}
          scanning={scanning}
          selectedDrive={selectedDrive}
          onSelectDrive={setSelectedDrive}
          onOpen={onOpen}
          onRecover={onRecover}
        />
      </div>
    </div>
  );
}
