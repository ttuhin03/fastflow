import React, {useState} from 'react';

/**
 * Erzeugt einen Fernet-kompatiblen Key (32 Bytes, Base64url) im Browser
 * und zeigt ihn mit Kopieren-Button an.
 */
function generateFernetKey(): string {
  const bytes = new Uint8Array(32);
  crypto.getRandomValues(bytes);
  let binary = '';
  for (let i = 0; i < bytes.length; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  const b64 = btoa(binary);
  return b64.replace(/\+/g, '-').replace(/\//g, '_');
}

export default function GenerateEncryptionKey(): React.ReactElement {
  const [key, setKey] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const handleGenerate = (): void => {
    setKey(generateFernetKey());
    setCopied(false);
  };

  const handleCopy = async (): Promise<void> => {
    if (!key) return;
    try {
      await navigator.clipboard.writeText(key);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Fallback in älteren Browsern optional
    }
  };

  return (
    <div style={{marginBottom: '1rem'}}>
      <button
        type="button"
        className="button button--primary"
        onClick={handleGenerate}
      >
        Schlüssel erzeugen
      </button>
      {key && (
        <div style={{marginTop: '0.75rem'}}>
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '0.5rem',
              flexWrap: 'wrap',
            }}
          >
            <code
              style={{
                padding: '0.4rem 0.6rem',
                background: 'var(--ifm-code-background)',
                borderRadius: 'var(--ifm-code-border-radius)',
                fontSize: '0.9em',
                wordBreak: 'break-all',
              }}
            >
              {key}
            </code>
            <button
              type="button"
              className="button button--secondary button--sm"
              onClick={handleCopy}
            >
              {copied ? 'Kopiert' : 'Kopieren'}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
