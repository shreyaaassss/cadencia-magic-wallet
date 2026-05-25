import * as React from 'react';
import { Copy, Check, X } from 'lucide-react';
import { Button } from '@/components/ui/button';

export interface LlmLog {
  id: string;
  session_id: string;
  round: number;
  agent: string;
  model: string;
  prompt_tokens: number;
  completion_tokens: number;
  latency_ms: number;
  status: string;
  created_at: string;
  prompt_summary: string;
  response_summary: string | null;
}

interface LlmLogDrawerProps {
  log: LlmLog | null;
  open: boolean;
  onClose: () => void;
}

export function LlmLogDrawer({ log, open, onClose }: LlmLogDrawerProps) {
  const [copiedSection, setCopiedSection] = React.useState<'prompt' | 'response' | null>(null);

  if (!open || !log) return null;

  const copyToClipboard = (text: string, section: 'prompt' | 'response') => {
    navigator.clipboard.writeText(text);
    setCopiedSection(section);
    setTimeout(() => setCopiedSection(null), 2000);
  };

  return (
    <>
      <div 
        className="fixed inset-0 bg-background/80 backdrop-blur-sm z-40 transition-opacity"
        onClick={onClose}
      />
      
      <div className="fixed inset-y-0 right-0 z-50 w-full max-w-lg bg-card border-l border-border shadow-2xl flex flex-col animate-in slide-in-from-right sm:max-w-lg">
        <div className="flex items-center justify-between p-6 border-b border-border">
          <div>
            <h3 className="text-lg font-semibold text-foreground">LLM Log</h3>
            <p className="text-sm text-muted-foreground font-mono mt-1">
              {log.session_id} &bull; Round {log.round} ({log.agent})
            </p>
          </div>
          <button 
            onClick={onClose}
            className="rounded-sm opacity-70 ring-offset-background transition-opacity hover:opacity-100 focus:outline-none bg-muted/30 p-2 border border-border mt-1"
          >
            <X className="h-4 w-4" />
            <span className="sr-only">Close</span>
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-6 space-y-6">
          <div className="grid grid-cols-2 gap-4 text-sm bg-muted/20 p-4 rounded-lg border border-border">
            <div>
              <span className="text-muted-foreground block text-xs mb-1">Model</span>
              <span className="font-mono">{log.model}</span>
            </div>
            <div>
              <span className="text-muted-foreground block text-xs mb-1">Status</span>
              <span className={log.status === 'SUCCESS' ? 'text-green-600' : 'text-destructive font-medium'}>
                {log.status}
              </span>
            </div>
            <div>
              <span className="text-muted-foreground block text-xs mb-1">Tokens (P/C)</span>
              <span className="font-mono">{log.prompt_tokens} / {log.completion_tokens}</span>
            </div>
            <div>
              <span className="text-muted-foreground block text-xs mb-1">Latency</span>
              <span className="font-mono">{log.latency_ms}ms</span>
            </div>
          </div>

          <div>
            <div className="flex justify-between items-center mb-2">
              <h4 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider">Prompt Summary</h4>
              <Button 
                variant="ghost" 
                size="sm" 
                className="h-6 text-xs text-muted-foreground"
                onClick={() => copyToClipboard(log.prompt_summary, 'prompt')}
              >
                {copiedSection === 'prompt' ? <Check className="h-3 w-3 mr-1 text-green-600" /> : <Copy className="h-3 w-3 mr-1" />}
                Copy
              </Button>
            </div>
            <div className="bg-muted p-4 rounded-lg border border-border text-xs font-mono whitespace-pre-wrap text-foreground/90 overflow-x-auto">
              {log.prompt_summary}
            </div>
          </div>

          <div>
            <div className="flex justify-between items-center mb-2">
              <h4 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider">Response Summary</h4>
              {log.response_summary && (
                <Button 
                  variant="ghost" 
                  size="sm" 
                  className="h-6 text-xs text-muted-foreground"
                  onClick={() => copyToClipboard(log.response_summary!, 'response')}
                >
                  {copiedSection === 'response' ? <Check className="h-3 w-3 mr-1 text-green-600" /> : <Copy className="h-3 w-3 mr-1" />}
                  Copy
                </Button>
              )}
            </div>
            <div className={`p-4 rounded-lg border text-xs font-mono whitespace-pre-wrap overflow-x-auto ${log.response_summary ? 'bg-muted border-border text-foreground/90' : 'bg-muted/10 border-dashed border-border/50 text-muted-foreground italic'}`}>
              {log.response_summary || 'No response generated (timeout/error).'}
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
