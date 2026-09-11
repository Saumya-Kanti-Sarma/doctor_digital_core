import { useState } from 'react';
import './RecoverySetup.css';

const FILE_TYPES = [
  { id: 'jpeg', label: 'JPEG / JPG images', icon: 'image' },
  { id: 'png',  label: 'PNG images',        icon: 'image2' },
  { id: 'text', label: 'TEXT files',        icon: 'text' },
];

export default function RecoverySetup({ drive, onCancel, onStartRecovery }) {
  const [checked, setChecked] = useState({ jpeg: true, png: true, text: true });
  const [outputDir, setOutputDir] = useState('C:\\Users\\serea\\recovered_files');

  function toggleType(id) {
    setChecked((prev) => ({ ...prev, [id]: !prev[id] }));
  }

  function handleStart() {
    const selectedTypes = Object.entries(checked)
      .filter(([, v]) => v)
      .map(([k]) => k);
    onStartRecovery?.({ drive, selectedTypes, outputDir });
  }

  return (
    <div className="recovery-wrapper">
      <div className="recovery-modal">
        {/* Title bar */}
        <div className="recovery-titlebar">
          <div className="recovery-titlebar__left">
            <img src="/usb-icon-small.svg" width="18" height="18" alt="" aria-hidden="true" />
            <span>Recovery Setup</span>
          </div>
          <div className="recovery-titlebar__controls">
            <button className="titlebar-btn" aria-label="Minimise">&#8211;</button>
            <button className="titlebar-btn" aria-label="Maximise">&#9645;</button>
            <button className="titlebar-btn titlebar-btn--close" aria-label="Close" onClick={onCancel}>&#10005;</button>
          </div>
        </div>

        {/* Blue hero banner */}
        <div className="recovery-hero">
          <div className="recovery-hero__icon">
            <GearIcon />
          </div>
          <h1 className="recovery-hero__title">Configure Recovery</h1>
        </div>

        {/* Body */}
        <div className="recovery-body">
          {/* File type selection */}
          <div className="recovery-section">
            <p className="recovery-section__label">Select file types to recover:</p>
            <div className="recovery-filetypes">
              {FILE_TYPES.map(({ id, label, icon }) => (
                <label key={id} className="filetype-row">
                  <span className={`filetype-checkbox${checked[id] ? ' filetype-checkbox--checked' : ''}`}
                    onClick={() => toggleType(id)}
                    role="checkbox"
                    aria-checked={checked[id]}
                    tabIndex={0}
                    onKeyDown={(e) => e.key === ' ' && toggleType(id)}
                  >
                    {checked[id] && <CheckIcon />}
                  </span>
                  <FileTypeIcon type={icon} />
                  <span className="filetype-label">{label}</span>
                </label>
              ))}
            </div>
          </div>

          {/* Output directory */}
          <div className="recovery-section recovery-section--dir">
            <p className="recovery-section__label">
              <FolderIcon /> Output directory <span className="recovery-section__hint">(on your system, not on USB):</span>
            </p>
            <div className="recovery-dir-row">
              <input
                type="text"
                className="recovery-dir-input"
                value={outputDir}
                onChange={(e) => setOutputDir(e.target.value)}
                aria-label="Output directory"
              />
              <button className="recovery-browse-btn">
                <FolderIcon /> Browse
              </button>
            </div>
          </div>
        </div>

        {/* Footer buttons */}
        <div className="recovery-footer">
          <button className="recovery-btn recovery-btn--start" onClick={handleStart}>
            <RecoverSpinIcon /> Start Recovery
          </button>
          <button className="recovery-btn recovery-btn--cancel" onClick={onCancel}>
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}

/* ── Icons ── */
function GearIcon() {
  return (
    <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="1.8"
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <circle cx="12" cy="12" r="3"/>
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>
    </svg>
  );
}

function CheckIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="3.5"
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <polyline points="20 6 9 17 4 12"/>
    </svg>
  );
}

function FileTypeIcon({ type }) {
  if (type === 'image' || type === 'image2') {
    return (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#1e4db7" strokeWidth="1.8"
        strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <rect x="3" y="3" width="18" height="18" rx="2"/>
        <circle cx="8.5" cy="8.5" r="1.5"/>
        <polyline points="21 15 16 10 5 21"/>
      </svg>
    );
  }
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#1e4db7" strokeWidth="1.8"
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
      <polyline points="14 2 14 8 20 8"/>
      <line x1="16" y1="13" x2="8" y2="13"/>
      <line x1="16" y1="17" x2="8" y2="17"/>
      <polyline points="10 9 9 9 8 9"/>
    </svg>
  );
}

function FolderIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>
    </svg>
  );
}

function RecoverSpinIcon() {
  return (
    <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.5"
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <polyline points="1 4 1 10 7 10"/>
      <path d="M3.51 15a9 9 0 1 0 .49-4.95"/>
    </svg>
  );
}
