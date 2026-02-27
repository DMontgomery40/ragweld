import { http, passthrough } from 'msw';

// Default passthrough handlers keep core web builds behavior-neutral.
const passthroughApi = http.all('/api/*', () => passthrough());

export const handlersPartial = [passthroughApi];
export const handlersFull = [passthroughApi];
