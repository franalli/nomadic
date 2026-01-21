/**
 * Stream Parser
 *
 * Buffered NDJSON parser for handling streaming responses.
 * Handles partial chunks across reads safely.
 */

import type { GenerationState } from '@/types/plan-envelope';
import type { PlanDocumentData } from '@/types/document';

/**
 * Stream event types from the backend.
 */
export type StreamEvent =
  | { type: 'progress'; stage: GenerationState['stage']; message?: string; pct?: number }
  | { type: 'envelope'; plan_envelope: Partial<PlanDocumentData> }
  | { type: 'done'; plan_view_state: string }
  | { type: 'error'; message: string };

/**
 * Creates a buffered NDJSON parser that handles partial chunks across reads.
 *
 * Usage:
 * ```ts
 * const parser = createStreamParser((event) => {
 *   if (event.type === 'envelope') {
 *     documentStore.mergeEnvelope(event.plan_envelope);
 *   } else if (event.type === 'progress') {
 *     setGeneration({ active: true, stage: event.stage, message: event.message, pct: event.pct });
 *   }
 * });
 *
 * while (true) {
 *   const { done, value } = await reader.read();
 *   if (done) break;
 *   parser.feed(decoder.decode(value, { stream: true }));
 * }
 * parser.flush();
 * ```
 */
export function createStreamParser(onEvent: (event: StreamEvent) => void) {
  let buffer = '';

  return {
    /**
     * Feed a chunk of data to the parser.
     * Handles partial lines by buffering until complete.
     */
    feed(chunk: string) {
      buffer += chunk;

      // NDJSON: split by newlines
      const lines = buffer.split('\n');
      // Keep last partial line in buffer (may be incomplete)
      buffer = lines.pop() || '';

      for (const line of lines) {
        if (!line.trim()) continue;
        try {
          const event = JSON.parse(line) as StreamEvent;
          onEvent(event);
        } catch (e) {
          console.error('Failed to parse stream line:', line, e);
        }
      }
    },

    /**
     * Flush any remaining data in the buffer.
     * Call this when the stream ends.
     */
    flush() {
      if (buffer.trim()) {
        try {
          const event = JSON.parse(buffer) as StreamEvent;
          onEvent(event);
        } catch (e) {
          console.error('Failed to parse final buffer:', buffer, e);
        }
        buffer = '';
      }
    },

    /**
     * Reset the parser state.
     */
    reset() {
      buffer = '';
    },
  };
}

/**
 * Helper to read a streaming response with the parser.
 * Returns a cleanup function to abort the stream.
 */
export async function readStreamingResponse(
  response: Response,
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal
): Promise<void> {
  if (!response.body) {
    throw new Error('Response body is null');
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  const parser = createStreamParser(onEvent);

  try {
    while (true) {
      if (signal?.aborted) {
        reader.cancel();
        break;
      }

      const { done, value } = await reader.read();
      if (done) break;

      parser.feed(decoder.decode(value, { stream: true }));
    }
    parser.flush();
  } finally {
    reader.releaseLock();
  }
}
