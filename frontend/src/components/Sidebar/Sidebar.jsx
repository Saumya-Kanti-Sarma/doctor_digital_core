import { Search } from 'lucide-react';
import './Sidebar.css';

export default function Sidebar({ onScan, scanning }) {
  return (
    <aside className="sidebar">
      <div className="sidebar__logo">
        <div className="sidebar__logo-icon">
          {/* Hat icon SVG */}
          <img src="/logo.png" id='logo' />
        </div>
        <div className="sidebar__logo-text">
          <span className="sidebar__logo-doctor">Doctor</span>
          <span className="sidebar__logo-digital">Digital</span>
        </div>
      </div>

      <button
        className={`sidebar__scan-btn${scanning ? ' sidebar__scan-btn--active' : ''}`}
        onClick={onScan}
      >
        <Search size={18} strokeWidth={2.5} />
        <span>{scanning ? 'Scanning…' : 'Scan for Drives'}</span>
      </button>

      <div className="sidebar__decorative">
        <img
          src="/shield-decoration.svg"
          alt=""
          aria-hidden="true"
          className="sidebar__shield-svg"
        />
      </div>
    </aside>
  );
}
