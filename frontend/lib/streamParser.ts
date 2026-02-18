/* eslint no-unused-vars: ["error", { "args": "none" }] */
/**
 * Stream Parser
 *
 * Buffered NDJSON parser for handling streaming responses.
 * Handles partial chunks across reads safely.
 */

import { debugLog } from '@/lib/debug';
import type { PlanDocumentData } from '@/types/document';
import type { GenerationState, PlanViewState } from '@/types/plan-envelope';

type StreamEnvelope = Partial<PlanDocumentData> & {
  generation?: GenerationState;
};

/**
 * Stream event types from the backend.
 */
export type StreamEvent =
  | { type: 'progress'; stage: GenerationState['stage']; message?: string; pct?: number }
  | { type: 'envelope'; plan_envelope: StreamEnvelope }
  | {
      type: 'done';
      plan_view_state: PlanViewState;
      dropped_preferred_count?: number;
      warnings?: string[];
      version?: number;
    }
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
        let event: StreamEvent;
        try {
          event = JSON.parse(line) as StreamEvent;
        } catch (e) {
          debugLog('Failed to parse stream line:', line, e);
          continue;
        }
        onEvent(event);
      }
    },

    /**
     * Flush any remaining data in the buffer.
     * Call this when the stream ends.
     */
    flush() {
      if (buffer.trim()) {
        let event: StreamEvent;
        try {
          event = JSON.parse(buffer) as StreamEvent;
        } catch (e) {
          debugLog('Failed to parse final buffer:', buffer, e);
          buffer = '';
          return;
        }
        onEvent(event);
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

type StreamDoneEvent = Extract<StreamEvent, { type: 'done' }>;
type StreamErrorEvent = Extract<StreamEvent, { type: 'error' }>;
type StreamProgressEvent = Extract<StreamEvent, { type: 'progress' }>;

type NdjsonEnvelopeCallbacks = {
  onEnvelope?(envelope: StreamEnvelope): void;
  onProgress?(event: StreamProgressEvent): void;
  onDone?(event: StreamDoneEvent): void;
  onError?(event: StreamErrorEvent): void;
  onUnknown?(event: StreamEvent): void;
};

/**
 * Consume NDJSON stream output from itinerary endpoints using shared parsing logic.
 * Accepts either a `Response` or a `ReadableStream`.
 */
export async function consumeNdjsonEnvelopeStream(
  source: Response | ReadableStream<Uint8Array>,
  callbacks: NdjsonEnvelopeCallbacks
): Promise<void> {
  const stream = source instanceof Response ? source.body : source;
  if (!stream) {
    throw new Error('Streaming response body is missing');
  }

  const reader = stream.getReader();
  const decoder = new TextDecoder();
  const parser = createStreamParser((event) => {
    switch (event.type) {
      case 'envelope':
        callbacks.onEnvelope?.(event.plan_envelope);
        return;
      case 'progress':
        callbacks.onProgress?.(event);
        return;
      case 'done':
        callbacks.onDone?.(event);
        return;
      case 'error':
        callbacks.onError?.(event);
        return;
      default:
        callbacks.onUnknown?.(event);
    }
  });

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    parser.feed(decoder.decode(value, { stream: true }));
  }
  parser.flush();
}
