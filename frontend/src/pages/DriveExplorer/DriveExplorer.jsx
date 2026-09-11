import { useState } from 'react';
import './DriveExplorer.css';

// Demo file tree for the selected drive
function buildDemoFiles(driveName) {
  return [
    { id: 1, name: 'Documents',   type: 'folder', size: '—',       modified: '2026-08-10' },
    { id: 2, name: 'Photos',      type: 'folder', size: '—',       modified: '2026-07-22' },
    { id: 3, name: 'README.txt',  type: 'text',   size: '4 KB',    modified: '2026-09-01' },
    { id: 4, name: 'backup.zip',  type: 'zip',    size: '128 MB',  modified: '2026-06-15' },
    { id: 5, name: 'photo1.jpg',  type: 'image',  size: '3.2 MB',  modified: '2026-05-30' },
    { id: 6, name: 'photo2.png',  type: 'image',  size: '1.8 MB',  modified: '2026-05-30' },
    { id: 7, name: 'report.txt',  type: 'text',   size: '12 KB',   modified: '2026-04-18' },
    { id: 8, name: 'data.csv',    type: 'text',   size: '56 KB',   modified: '2026-03-07' },
  ];
}

export default function DriveExplorer({ drive, onBack }) {
  const files = buildDemoFiles(drive?.model);
  const [selected, setSelected] = useState(null);

  return (
    <div className="explorer-wrapper">
      <div className="explorer">
        {/* Title bar */}
        <div className="explorer__titlebar">
          <div className="explorer__titlebar-left">
            <img src="/usb-icon-small.svg" width="16" height="16" alt="" aria-hidden="true" />
            <span>{drive?.model ?? 'USB Drive'} — File Explorer</span>
          </div>
          <button className="explorer__close-btn" onClick={onBack} aria-label="Close">&#10005;</button>
        </div>

        {/* Header */}
        <div className="explorer__header">
          <button className="explorer__back-btn" onClick={onBack}>
            <BackIcon /> Back to Dashboard
          </button>
          <div className="explorer__drive-badge">
            <img src="/usb-icon-small.svg" width="16" height="16" alt="" aria-hidden="true" />
            <span>{drive?.model}</span>
            <span className="explorer__drive-sep">·</span>
            <span>{drive?.size}</span>
            <span className={`explorer__status-dot explorer__status-dot--${drive?.status?.toLowerCase() ?? 'unknown'}`} />
            <span className="explorer__status-label">{drive?.status}</span>
          </div>
        </div>

        {/* Column headers */}
        <div className="explorer__cols">
          <span className="explorer__col"><FileColIcon /> Name</span>
          <span className="explorer__col">Type</span>
          <span className="explorer__col">Size</span>
          <span className="explorer__col">Modified</span>
        </div>

        {/* File list */}
        <div className="explorer__body">
          {files.map((file) => (
            <div
              key={file.id}
              className={`explorer__row${selected === file.id ? ' explorer__row--selected' : ''}`}
              onClick={() => setSelected(file.id)}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => e.key === 'Enter' && setSelected(file.id)}
            >
              <span className="explorer__cell explorer__cell--name">
                <FileIcon type={file.type} />
                {file.name}
              </span>
              <span className="explorer__cell explorer__cell--type">{file.type}</span>
              <span className="explorer__cell">{file.size}</span>
              <span className="explorer__cell">{file.modified}</span>
            </div>
          ))}
        </div>

        {/* Footer */}
        <div className="explorer__footer">
          <span>{files.length} items</span>
          {selected && (
            <span className="explorer__selected-label">
              Selected: <strong>{files.find((f) => f.id === selected)?.name}</strong>
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

/* ── Icons ── */
function BackIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <polyline points="15 18 9 12 15 6"/>
    </svg>
  );
}

function FileColIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
      <polyline points="14 2 14 8 20 8"/>
    </svg>
  );
}

function FileIcon({ type }) {
  const color = {
    folder: '#f59e0b',
    image:  '#8b5cf6',
    zip:    '#0ea5e9',
    text:   '#64748b',
  }[type] ?? '#64748b';

  if (type === 'folder') {
    return (
      <svg width="18" height="18" viewBox="0 0 24 24" fill={color} stroke={color}
        strokeWidth="1" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>
      </svg>
    );
  }
  if (type === 'image') {
    return (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke={color}
        strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <rect x="3" y="3" width="18" height="18" rx="2"/>
        <circle cx="8.5" cy="8.5" r="1.5"/>
        <polyline points="21 15 16 10 5 21"/>
      </svg>
    );
  }
  if (type === 'zip') {
    return (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke={color}
        strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
        <polyline points="14 2 14 8 20 8"/>
        <line x1="12" y1="11" x2="12" y2="17"/>
        <line x1="9" y1="14" x2="15" y2="14"/>
      </svg>
    );
  }
  // default: text/csv
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke={color}
      strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
      <polyline points="14 2 14 8 20 8"/>
      <line x1="16" y1="13" x2="8" y2="13"/>
      <line x1="16" y1="17" x2="8" y2="17"/>
      <polyline points="10 9 9 9 8 9"/>
    </svg>
  );
}
