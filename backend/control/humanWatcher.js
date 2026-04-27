import { appendApprovedEntry } from '../deltavault/ledger.js';
import { dataBus } from './eventBus.js';

dataBus.on('HUMAN.INPUT', (event) => {
  appendApprovedEntry({
    actionType: 'human:observed-input',
    payload: { source: event.payload?.source || 'unknown', action: event.payload?.action || '', details: event.payload || null },
    reason: 'Human action observed outside Emma control.',
  });
});
