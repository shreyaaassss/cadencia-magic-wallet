'use client';

import { useEffect, useRef, useState, useCallback } from 'react';
import { getAccessToken } from '@/lib/api';
import { API_BASE_URL } from '@/lib/constants';

interface UseSSEProps {
  sessionId: string;
  onEvent: (event: string, data: unknown) => void;
  enabled?: boolean;
}

export function useSSE({ sessionId, onEvent, enabled = true }: UseSSEProps) {
  const [isConnected, setIsConnected] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const onEventRef = useRef(onEvent);
  const lastEventIdRef = useRef<string | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reconnectDelayRef = useRef(1000);
  onEventRef.current = onEvent;

  const connect = useCallback(async () => {
    if (!sessionId || !enabled) return;

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const token = getAccessToken();
      const headers: Record<string, string> = {};
      if (token) headers['Authorization'] = `Bearer ${token}`;

      // Include last event ID for reconnect replay
      let url = `${API_BASE_URL}/v1/sessions/${sessionId}/stream`;
      if (lastEventIdRef.current) {
        url += `?last_event_id=${encodeURIComponent(lastEventIdRef.current)}`;
      }

      const response = await fetch(url, {
        headers,
        signal: controller.signal,
      });

      if (!response.ok || !response.body) {
        setIsConnected(false);
        return;
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      setIsConnected(true);
      reconnectDelayRef.current = 1000; // Reset backoff on successful connection

      let buffer = '';
      let currentEvent = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split('\n');
        buffer = parts.pop() ?? '';

        for (const line of parts) {
          const trimmed = line.trim();
          if (trimmed.startsWith('id: ')) {
            lastEventIdRef.current = trimmed.slice(4);
          } else if (trimmed.startsWith('event: ')) {
            currentEvent = trimmed.slice(7);
          } else if (trimmed.startsWith('data: ')) {
            const raw = trimmed.slice(6);
            try {
              const data = JSON.parse(raw);
              if (currentEvent) {
                onEventRef.current(currentEvent, data);
              }
            } catch {
              // Skip malformed JSON
            }
            currentEvent = '';
          }
        }
      }
    } catch (err: unknown) {
      if (err instanceof DOMException && err.name === 'AbortError') return;
      console.error('SSE connection error:', err);
    } finally {
      setIsConnected(false);
      // Auto-reconnect with exponential backoff if still enabled
      if (enabled) {
        const delay = Math.min(reconnectDelayRef.current, 30000);
        reconnectDelayRef.current = Math.min(delay * 2, 30000);
        reconnectTimerRef.current = setTimeout(() => connect(), delay);
      }
    }
  }, [sessionId, enabled]);

  useEffect(() => {
    connect();
    return () => {
      abortRef.current?.abort();
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
    };
  }, [connect]);

  const reconnect = useCallback(() => {
    abortRef.current?.abort();
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
    reconnectDelayRef.current = 1000;
    setTimeout(() => connect(), 1000);
  }, [connect]);

  return { isConnected, reconnect };
}
