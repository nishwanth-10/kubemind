'use client';
import { useEffect, useRef, useState, useCallback } from 'react';
import { WSPayload } from '@/types';

const WS_URL = (process.env.NEXT_PUBLIC_WS_URL || '').trim() || 'ws://localhost:8000/ws';

export function useKubeMindWS() {
  const [data, setData]       = useState<WSPayload | null>(null);
  const [status, setStatus]   = useState<'connecting' | 'open' | 'closed'>('connecting');
  const [lastTs, setLastTs]   = useState<string>('');
  const ws   = useRef<WebSocket | null>(null);
  const retry = useRef<ReturnType<typeof setTimeout> | null>(null);
  const isMounted = useRef(true);

  const connect = useCallback(() => {
    if (!isMounted.current) return;
    setStatus('connecting');

    const token = typeof window !== 'undefined' ? localStorage.getItem('kubemind_token') : null;
    const wsUrlWithToken = token ? `${WS_URL}?token=${token}` : WS_URL;
    const socket = new WebSocket(wsUrlWithToken);

    socket.onopen = () => {
      if (!isMounted.current) return;
      setStatus('open');
      if (retry.current) { clearTimeout(retry.current); retry.current = null; }
    };

    socket.onmessage = (e) => {
      if (!isMounted.current) return;
      try {
        const payload: WSPayload = JSON.parse(e.data);
        if (payload.type === 'METRICS_UPDATE') {
          setData(payload);
          setLastTs(payload.ts);
        }
      } catch { /* ignore parse errors */ }
    };

    socket.onclose = () => {
      if (!isMounted.current) return;
      setStatus('closed');
      retry.current = setTimeout(connect, 3000);
    };

    socket.onerror = () => { socket.close(); };

    ws.current = socket;
  }, []);

  useEffect(() => {
    isMounted.current = true;
    connect();
    return () => {
      isMounted.current = false;
      if (retry.current) clearTimeout(retry.current);
      ws.current?.close();
    };
  }, [connect]);

  const send = useCallback((msg: object) => {
    if (ws.current?.readyState === WebSocket.OPEN) {
      ws.current.send(JSON.stringify(msg));
    }
  }, []);

  const injectFault = useCallback((service: string, fault_type: string, duration = 120) => {
    send({ action: 'inject_fault', service, fault_type, duration });
  }, [send]);

  const clearFault = useCallback((service: string) => {
    send({ action: 'clear_fault', service });
  }, [send]);

  const askAI = useCallback((query: string) => {
    send({ action: 'ai_query', query });
  }, [send]);

  return { data, status, lastTs, injectFault, clearFault, askAI, send };
}
