import { EventEmitter } from 'node:events';
import crypto from 'node:crypto';

export const EVENT_CATEGORIES = {
  HUMAN: 'HUMAN.INPUT',
  LUCY: 'LUCY.ACTION',
  SYSTEM: 'SYSTEM',
};

export const dataBus = new EventEmitter();
dataBus.setMaxListeners(100);

export function emitEvent(type, payload, source = 'LUCY_CORE') {
  const event = {
    id: crypto.randomUUID(),
    type,
    payload,
    timestamp: Date.now(),
    source,
  };
  dataBus.emit(type, event);
  dataBus.emit('*', event);
  return event;
}
