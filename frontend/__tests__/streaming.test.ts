/**
 * NDJSON Stream Parser Tests
 *
 * Tests for createStreamParser() — the buffered NDJSON parser
 * that handles partial chunks across ReadableStream reads.
 */

import { describe, expect, it, vi } from 'vitest';

import { createStreamParser, type StreamEvent } from '@/lib/streamParser';

describe('createStreamParser', () => {
  it('parses complete NDJSON lines and dispatches events', () => {
    const events: StreamEvent[] = [];
    const parser = createStreamParser((e) => events.push(e));

    parser.feed(
      '{"type":"progress","stage":"structure","message":"Starting"}\n' +
      '{"type":"done","plan_view_state":"S2_STRATEGY_READY"}\n'
    );

    expect(events).toHaveLength(2);
    expect(events[0]).toMatchObject({ type: 'progress', stage: 'structure', message: 'Starting' });
    expect(events[1]).toMatchObject({ type: 'done', plan_view_state: 'S2_STRATEGY_READY' });
  });

  it('buffers partial lines across multiple feed calls', () => {
    const events: StreamEvent[] = [];
    const parser = createStreamParser((e) => events.push(e));

    // First chunk: incomplete JSON line
    parser.feed('{"type":"progress","sta');
    expect(events).toHaveLength(0);

    // Second chunk: completes the line
    parser.feed('ge":"structure"}\n');
    expect(events).toHaveLength(1);
    expect(events[0]).toMatchObject({ type: 'progress', stage: 'structure' });
  });

  it('skips malformed JSON without throwing', () => {
    const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    const events: StreamEvent[] = [];
    const parser = createStreamParser((e) => events.push(e));

    parser.feed('not-valid-json\n{"type":"done","plan_view_state":"S0_EMPTY"}\n');

    expect(events).toHaveLength(1);
    expect(events[0]).toMatchObject({ type: 'done', plan_view_state: 'S0_EMPTY' });
    expect(consoleSpy).toHaveBeenCalledOnce();

    consoleSpy.mockRestore();
  });

  it('flush() processes remaining complete JSON in buffer', () => {
    const events: StreamEvent[] = [];
    const parser = createStreamParser((e) => events.push(e));

    // Feed valid JSON without trailing newline — stays in buffer
    parser.feed('{"type":"progress","stage":"itinerary"}');
    expect(events).toHaveLength(0);

    parser.flush();
    expect(events).toHaveLength(1);
    expect(events[0]).toMatchObject({ type: 'progress', stage: 'itinerary' });
  });

  it('accepts done events without plan_view_state for duplicate no-op acks', () => {
    const events: StreamEvent[] = [];
    const parser = createStreamParser((e) => events.push(e));

    parser.feed('{"type":"done","message":"duplicate_noop"}\n');

    expect(events).toHaveLength(1);
    expect(events[0]).toMatchObject({ type: 'done', message: 'duplicate_noop' });
  });
});
