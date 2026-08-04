/**
 * Handles Upstox OAuth redirect: extracts code + state from URL,
 * calls POST /api/upstox/token, then navigates back to module1.
 */
import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Loader2, CheckCircle, XCircle } from 'lucide-react';
import { exchangeToken } from '@/api/upstox';
import { extractError } from '@/api/client';

export function OAuthCallback() {
  const navigate = useNavigate();
  const [status, setStatus] = useState<'loading' | 'success' | 'error'>('loading');
  const [error, setError] = useState('');

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const code = params.get('code');
    const state = params.get('state') ?? undefined;

    if (!code) {
      setError('No authorization code received from Upstox.');
      setStatus('error');
      return;
    }

    exchangeToken(code, state)
      .then(() => {
        setStatus('success');
        setTimeout(() => navigate('/module1', { replace: true }), 1500);
      })
      .catch((err) => {
        setError(extractError(err));
        setStatus('error');
      });
  }, [navigate]);

  return (
    <div className="min-h-screen flex items-center justify-center bg-background">
      <div className="flex flex-col items-center gap-4 text-center max-w-sm">
        {status === 'loading' && (
          <>
            <Loader2 className="size-10 animate-spin text-primary" />
            <p className="text-muted-foreground">Completing Upstox authentication…</p>
          </>
        )}
        {status === 'success' && (
          <>
            <CheckCircle className="size-10 text-green-500" />
            <p className="font-medium">Connected to Upstox!</p>
            <p className="text-sm text-muted-foreground">Redirecting…</p>
          </>
        )}
        {status === 'error' && (
          <>
            <XCircle className="size-10 text-destructive" />
            <p className="font-medium">Authentication failed</p>
            <p className="text-sm text-muted-foreground">{error}</p>
            <button
              onClick={() => navigate('/module1', { replace: true })}
              className="text-sm text-primary underline underline-offset-2"
            >
              Go back
            </button>
          </>
        )}
      </div>
    </div>
  );
}
