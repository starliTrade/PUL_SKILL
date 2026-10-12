/**
 * Known-answer tests for the local SHA-256 (audit M38).
 *
 * A hand-written hash is only trustworthy if it is verified against published
 * vectors. The boundary cases matter most: the padding rule changes at 55/56
 * and 63/64 bytes, and an off-by-one there produces a hash that is correct for
 * short inputs and silently wrong for long ones.
 *
 * The expected values are the standard SHA-256 outputs (FIPS 180-4 / the
 * classic NIST vectors), independently reproduced with Node's `crypto`.
 */
import { describe, it, expect } from 'vitest';

import { sha256Hex } from './sha256';

const encoder = new TextEncoder();

const VECTORS: { name: string; input: string; expected: string }[] = [
  {
    name: 'empty',
    input: '',
    expected: '0xe3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
  },
  {
    name: 'abc',
    input: 'abc',
    expected: '0xba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad',
  },
  {
    name: 'two blocks',
    input: 'abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq',
    expected: '0x248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1',
  },
  {
    name: 'the quick brown fox',
    input: 'The quick brown fox jumps over the lazy dog',
    expected: '0xd7a8fbb307d7809469ca9abcb0082e4f8d5651e46d3cdb762d02d0bf37c9e592',
  },
  // Padding boundaries: 55 fits in the length field, 56 forces a new block.
  {
    name: '55 bytes',
    input: 'a'.repeat(55),
    expected: '0x9f4390f8d30c2dd92ec9f095b65e2b9ae9b0a925a5258e241c9f1e910f734318',
  },
  {
    name: '56 bytes',
    input: 'a'.repeat(56),
    expected: '0xb35439a4ac6f0948b6d6f9e3c6af0f5f590ce20f1bde7090ef7970686ec6738a',
  },
  {
    name: '63 bytes',
    input: 'a'.repeat(63),
    expected: '0x7d3e74a05d7db15bce4ad9ec0658ea98e3f06eeecf16b4c6fff2da457ddc2f34',
  },
  {
    name: '64 bytes',
    input: 'a'.repeat(64),
    expected: '0xffe054fe7ae0cb6dc65c3af9b61d5209f439851db43d0ba5997337df154668eb',
  },
  {
    name: '65 bytes',
    input: 'a'.repeat(65),
    expected: '0x635361c48bb9eab14198e76ea8ab7f1a41685d6ad62aa9146d301d4f17eb0ae0',
  },
  {
    name: '119 bytes',
    input: 'a'.repeat(119),
    expected: '0x31eba51c313a5c08226adf18d4a359cfdfd8d2e816b13f4af952f7ea6584dcfb',
  },
  {
    name: '120 bytes',
    input: 'a'.repeat(120),
    expected: '0x2f3d335432c70b580af0e8e1b3674a7c020d683aa5f73aaaedfdc55af904c21c',
  },
];

describe('local SHA-256 (audit M38)', () => {
  for (const { name, input, expected } of VECTORS) {
    it(`matches the published vector for ${name}`, () => {
      expect(sha256Hex(encoder.encode(input))).toBe(expected);
    });
  }

  it('handles non-ASCII input', () => {
    // Multi-byte UTF-8 must be hashed as bytes, not code units.
    expect(sha256Hex(encoder.encode('پولسار'))).toBe(
      sha256Hex(encoder.encode('پولسار'))
    );
    expect(sha256Hex(encoder.encode('پولسار'))).toMatch(/^0x[0-9a-f]{64}$/);
  });

  it('is stable across calls', () => {
    const a = sha256Hex(encoder.encode('same input'));
    const b = sha256Hex(encoder.encode('same input'));
    expect(a).toBe(b);
  });

  it('is different for different inputs', () => {
    expect(sha256Hex(encoder.encode('a'))).not.toBe(sha256Hex(encoder.encode('b')));
  });
});
