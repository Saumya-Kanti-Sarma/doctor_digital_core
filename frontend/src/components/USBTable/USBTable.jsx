import { Usb } from 'lucide-react';
import './USBTable.css';

export default function USBTable({ drives = [], selectedDrive, onSelectDrive, onOpen, onRecover }) {
  return (
    <section className="usb-table">
      {/* Panel header */}
      <div className="usb-table__header">
        <Usb size={20} strokeWidth={2} className="usb-table__header-icon" />
        <h2 className="usb-table__title">Connected USB drives</h2>
      </div>

      {/* Column headers */}
      <div className="usb-table__cols">
        <span className="usb-table__col-label">
          <ColIcon type="drive" /> Model
        </span>
        <span className="usb-table__col-label">
          <ColIcon type="serial" /> Serial
        </span>
        <span className="usb-table__col-label">
          <ColIcon type="size" /> Size
        </span>
        <span className="usb-table__col-label">
          <ColIcon type="status" /> Status
        </span>
      </div>

      {/* Body */}
      <div className="usb-table__body">
        {drives.length === 0 ? (
          <EmptyState />
        ) : (
          drives.map((drive, i) => (
            <DriveRow
              key={drive.serial ?? i}
              drive={drive}
              selected={selectedDrive?.serial === drive.serial}
              onSelect={() => onSelectDrive(drive)}
            />
          ))
        )}
      </div>

      {/* Bottom bar: drive info + action buttons */}
      {drives.length > 0 && (
        <div className="usb-table__footer">
          <div className="usb-table__drive-info">
            <img src="/usb-icon-small.svg" width="20" height="20" alt="" aria-hidden="true" />
            {selectedDrive ? (
              <span>
                Drive 1:&nbsp;<strong>{selectedDrive.model}</strong>
                &nbsp;&nbsp;Serial:&nbsp;{selectedDrive.serial}
                &nbsp;&nbsp;Size:&nbsp;{selectedDrive.size}
                &nbsp;&nbsp;Status:&nbsp;{selectedDrive.status}
              </span>
            ) : (
              <span className="usb-table__no-selection">Select a drive above</span>
            )}
          </div>

          <div className="usb-table__actions">
            <button
              className="action-btn action-btn--open"
              onClick={() => onOpen?.(selectedDrive)}
              disabled={!selectedDrive}
            >
              <FolderIcon /> Open
            </button>
            <button
              className="action-btn action-btn--recover"
              onClick={() => onRecover?.(selectedDrive)}
              disabled={!selectedDrive}
            >
              <RecoverIcon /> Recover
            </button>
            <button className="action-btn action-btn--sanitize">
              <SanitizeIcon /> Complete Sanitize
            </button>
          </div>
        </div>
      )}
    </section>
  );
}

/* ── Sub-components ── */

function EmptyState() {
  return (
    <div className="usb-empty">
      <div className="usb-empty__icon-wrap">
        <img src="/usb-scan-empty.svg" width="90" height="90" alt="" aria-hidden="true" />
      </div>
      <p className="usb-empty__title">No drives detected.</p>
      <p className="usb-empty__subtitle">Click "Scan for drives" to begin</p>
    </div>
  );
}

function DriveRow({ drive, selected, onSelect }) {
  return (
    <div
      className={`drive-row${selected ? ' drive-row--selected' : ''}`}
      onClick={onSelect}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => e.key === 'Enter' && onSelect()}
    >
      {/* Model cell — USB icon + name */}
      <span className="drive-row__cell drive-row__model">
        <img src="/usb-icon-small.svg" width="18" height="18" alt="" aria-hidden="true" />
        {drive.model}
      </span>
      <span className="drive-row__cell">{drive.serial}</span>
      <span className="drive-row__cell">{drive.size}</span>
      {/* Status cell — green dot + label */}
      <span className="drive-row__cell drive-row__status-cell">
        <span
          className={`drive-row__dot drive-row__dot--${drive.status?.toLowerCase() ?? 'unknown'}`}
        />
        <span className={`drive-row__status-text drive-row__status-text--${drive.status?.toLowerCase() ?? 'unknown'}`}>
          {drive.status}
        </span>
      </span>
    </div>
  );
}

/* ── Column header icons (inline SVG kept tiny) ── */
function ColIcon({ type }) {
  switch (type) {
    case 'drive':
      return (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <rect x="2" y="6" width="20" height="12" rx="2"/>
          <circle cx="17" cy="12" r="1" fill="currentColor"/>
          <path d="M6 12h6"/>
        </svg>
      );
    case 'serial':
      return (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
          <path d="M4 6h1v12H4z"/><path d="M7 6h1v12H7z"/><path d="M11 6h2v12h-2z"/>
          <path d="M15 6h1v12h-1z"/><path d="M18 6h2v12h-2z"/>
        </svg>
      );
    case 'size':
      return (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <ellipse cx="12" cy="5" rx="9" ry="3"/>
          <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/>
          <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/>
        </svg>
      );
    case 'status':
      return (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <circle cx="12" cy="12" r="10"/>
          <polyline points="12 6 12 12 16 14"/>
        </svg>
      );
    default:
      return null;
  }
}

/* ── Button icons ── */
function FolderIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>
    </svg>
  );
}

function RecoverIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <polyline points="1 4 1 10 7 10"/>
      <path d="M3.51 15a9 9 0 1 0 .49-4.95"/>
    </svg>
  );
}

function SanitizeIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6"/>
      <path d="M10 11v6M14 11v6"/>
    </svg>
  );
}
