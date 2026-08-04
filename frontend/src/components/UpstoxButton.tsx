/**
 * Upstox connection button — 3-state per PRD §2.1:
 *   State 1 — no credentials: shows "Add Upstox Account" → opens modal
 *   State 2 — credentials saved, not connected: shows "Connect to Upstox" → OAuth redirect
 *   State 3 — connected: shows "✓ Upstox Connected" with optional disconnect
 */
import { useState } from 'react';
import { Wifi, WifiOff, Plus, Loader2, LogOut } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  useUpstoxStatus,
  useSaveCredentials,
  useConnectUpstox,
  useDisconnectUpstox,
} from '@/hooks/useUpstox';

export function UpstoxButton() {
  const { data: status, isLoading } = useUpstoxStatus();
  const saveMutation = useSaveCredentials();
  const connectMutation = useConnectUpstox();
  const disconnectMutation = useDisconnectUpstox();

  const [modalOpen, setModalOpen] = useState(false);
  const [form, setForm] = useState({ api_key: '', api_secret: '', redirect_uri: 'http://localhost:5173/oauth/callback' });

  if (isLoading) {
    return (
      <Button variant="outline" size="sm" disabled>
        <Loader2 className="size-4 animate-spin" />
        Loading…
      </Button>
    );
  }

  // State 3 — Connected
  if (status?.is_connected) {
    return (
      <div className="flex items-center gap-2">
        <span className="flex items-center gap-1.5 text-sm text-green-600 dark:text-green-400 font-medium">
          <Wifi className="size-4" />
          Upstox Connected
        </span>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => disconnectMutation.mutate()}
          disabled={disconnectMutation.isPending}
          title="Disconnect"
        >
          <LogOut className="size-4" />
        </Button>
      </div>
    );
  }

  // State 2 — Credentials saved
  if (status?.has_credentials) {
    return (
      <Button
        variant="outline"
        size="sm"
        onClick={() => connectMutation.mutate()}
        disabled={connectMutation.isPending}
      >
        {connectMutation.isPending ? (
          <Loader2 className="size-4 animate-spin" />
        ) : (
          <WifiOff className="size-4" />
        )}
        Connect to Upstox
      </Button>
    );
  }

  // State 1 — No credentials
  return (
    <>
      <Button variant="outline" size="sm" onClick={() => setModalOpen(true)}>
        <Plus className="size-4" />
        Add Upstox Account
      </Button>

      <Dialog open={modalOpen} onOpenChange={setModalOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>Add Upstox Account</DialogTitle>
            <DialogDescription>
              Enter your Upstox API credentials. These are saved locally on the server in{' '}
              <code className="text-xs bg-muted px-1 py-0.5 rounded">upstox_config.txt</code>.
            </DialogDescription>
          </DialogHeader>

          <div className="grid gap-4 py-2">
            <div className="grid gap-1.5">
              <Label htmlFor="api_key">API Key</Label>
              <Input
                id="api_key"
                placeholder="Your Upstox API Key"
                value={form.api_key}
                onChange={(e) => setForm((f) => ({ ...f, api_key: e.target.value }))}
              />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="api_secret">API Secret</Label>
              <Input
                id="api_secret"
                type="password"
                placeholder="Your Upstox API Secret"
                value={form.api_secret}
                onChange={(e) => setForm((f) => ({ ...f, api_secret: e.target.value }))}
              />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="redirect_uri">Redirect URL</Label>
              <Input
                id="redirect_uri"
                placeholder="http://localhost:5173/oauth/callback"
                value={form.redirect_uri}
                onChange={(e) => setForm((f) => ({ ...f, redirect_uri: e.target.value }))}
              />
              <p className="text-xs text-muted-foreground">
                Must match the redirect URI registered in your Upstox app.
              </p>
            </div>
          </div>

          <div className="flex justify-end gap-2 pt-2">
            <Button variant="outline" onClick={() => setModalOpen(false)}>
              Cancel
            </Button>
            <Button
              onClick={() => {
                saveMutation.mutate(form, {
                  onSuccess: () => setModalOpen(false),
                });
              }}
              disabled={!form.api_key || !form.api_secret || !form.redirect_uri || saveMutation.isPending}
            >
              {saveMutation.isPending && <Loader2 className="size-4 animate-spin" />}
              Save
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
