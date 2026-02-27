import { setupWorker } from 'msw/browser';

// Base worker scaffold. Hosted demo fixtures can override this tree downstream.
export const worker = setupWorker();
