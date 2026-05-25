import * as React from 'react';
import { Send, CheckCircle2, AlertCircle } from 'lucide-react';
import { Button } from '@/components/ui/button';

export interface BroadcastPayload {
  target: string;
  priority: string;
  message: string;
}

interface BroadcastFormProps {
  onSend: (data: BroadcastPayload) => void;
  isSending: boolean;
  lastResult: { message_id: string; recipients: number } | null;
}

export function BroadcastForm({ onSend, isSending, lastResult }: BroadcastFormProps) {
  const [target, setTarget] = React.useState('all');
  const [priority, setPriority] = React.useState('normal');
  const [message, setMessage] = React.useState('');

  const handleSend = () => {
    if (!message.trim()) return;
    onSend({ target, priority, message });
    setMessage(''); // Clear on submit attempt
  };

  const isUrgent = priority === 'urgent';
  const isSystem = priority === 'system';

  return (
    <div className="bg-card border border-border rounded-lg p-6 max-w-2xl">
      <div className="mb-6">
        <h3 className="text-lg font-semibold text-foreground flex items-center gap-2">
          <Send className="h-5 w-5 text-primary" />
          Platform Broadcast
        </h3>
        <p className="text-sm text-muted-foreground mt-1">
          Send a notification to all or specific users on the platform
        </p>
      </div>

      <div className="space-y-4 mb-6">
        <div className="grid grid-cols-2 gap-4">
          <div className="flex flex-col gap-1">
            <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Target Audience</label>
            <select 
              className="bg-muted border border-border rounded-md text-sm px-3 py-2 outline-none w-full"
              value={target}
              onChange={(e) => setTarget(e.target.value)}
            >
              <option value="all">All Users</option>
              <option value="enterprises">Active Enterprises</option>
              <option value="admins">Admins Only</option>
            </select>
          </div>
          
          <div className="flex flex-col gap-1">
            <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Priority Level</label>
            <select 
              className="bg-muted border border-border rounded-md text-sm px-3 py-2 outline-none w-full"
              value={priority}
              onChange={(e) => setPriority(e.target.value)}
            >
              <option value="normal">Normal</option>
              <option value="urgent">Urgent</option>
              <option value="system">System</option>
            </select>
          </div>
        </div>

        <div className="flex flex-col gap-1">
          <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Message</label>
          <textarea 
            className="bg-muted border border-border rounded-md text-sm px-3 py-2 outline-none min-h-[100px] resize-none"
            placeholder="Enter broadcast message..."
            value={message}
            onChange={(e) => setMessage(e.target.value)}
          />
        </div>
      </div>

      <div className="mb-6">
        <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider block mb-2">Message Preview</label>
        <div className={`p-4 rounded-md text-sm ${
          isUrgent ? 'bg-amber-50 border border-amber-200 text-amber-800' :
          isSystem ? 'bg-muted/70 border border-border text-muted-foreground' : 
          'bg-card border border-border text-foreground'
        }`}>
          {isUrgent && <div className="flex items-center gap-1.5 text-amber-500 font-bold mb-2 text-xs uppercase tracking-wider max-w-fit px-2 py-0.5 rounded bg-amber-50"><AlertCircle className="h-3 w-3" /> Urgent Notice</div>}
          {isSystem && <div className="text-muted-foreground font-semibold mb-2 text-xs uppercase tracking-wider">System Announcement</div>}
          <div className="whitespace-pre-wrap">{message || 'Your message will appear here...'}</div>
        </div>
      </div>

      <div className="flex items-center justify-between border-t border-border pt-6">
        <div>
          {lastResult && (
            <span className="flex items-center gap-1.5 text-sm text-green-600 bg-green-50 px-3 py-1.5 rounded-md border border-green-200">
              <CheckCircle2 className="h-4 w-4" />
              Delivered to {lastResult.recipients} users
            </span>
          )}
        </div>
        <Button 
          onClick={handleSend} 
          disabled={!message.trim() || isSending}
          className="bg-primary text-primary-foreground min-w-[150px]"
        >
          {isSending ? 'Sending...' : `Send to ${target === 'all' ? 'All' : target === 'enterprises' ? 'Enterprises' : 'Admins'}`}
        </Button>
      </div>
    </div>
  );
}
