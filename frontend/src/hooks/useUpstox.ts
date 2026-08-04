import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import {
  getUpstoxStatus,
  saveCredentials,
  getAuthUrl,
  disconnect,
  type UpstoxCredentials,
} from '@/api/upstox';
import { extractError } from '@/api/client';

export function useUpstoxStatus() {
  return useQuery({
    queryKey: ['upstox-status'],
    queryFn: getUpstoxStatus,
    refetchInterval: 30_000,
  });
}

export function useSaveCredentials() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (creds: UpstoxCredentials) => saveCredentials(creds),
    onSuccess: () => {
      toast.success('Credentials saved');
      qc.invalidateQueries({ queryKey: ['upstox-status'] });
    },
    onError: (err) => toast.error(extractError(err)),
  });
}

export function useConnectUpstox() {
  return useMutation({
    mutationFn: async () => {
      const url = await getAuthUrl();
      window.location.href = url;
    },
    onError: (err) => toast.error(extractError(err)),
  });
}

export function useDisconnectUpstox() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: disconnect,
    onSuccess: () => {
      toast.success('Disconnected from Upstox');
      qc.invalidateQueries({ queryKey: ['upstox-status'] });
    },
    onError: (err) => toast.error(extractError(err)),
  });
}
