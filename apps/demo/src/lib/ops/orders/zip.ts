/**
 * A minimal ZIP reader for `.xlsx` files (stored and deflate entries, no ZIP64, no encryption),
 * so the browser module needs no dependency. Inflating uses the platform's `DecompressionStream`
 * (Chrome 80+, Safari 16.4+, Firefox 113+).
 */

export interface ZipEntry {
  readonly name: string;
  readonly method: number;
  readonly compressedSize: number;
  readonly localOffset: number;
}

const EOCD = 0x06054b50;
const CENTRAL = 0x02014b50;
const LOCAL = 0x04034b50;

export class ZipError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ZipError";
  }
}

function view(bytes: Uint8Array): DataView {
  return new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
}

export function listZip(bytes: Uint8Array): Map<string, ZipEntry> {
  const dv = view(bytes);
  let eocd = -1;
  for (let i = bytes.length - 22; i >= Math.max(0, bytes.length - 22 - 0xffff); i -= 1) {
    if (dv.getUint32(i, true) === EOCD) {
      eocd = i;
      break;
    }
  }
  if (eocd < 0) throw new ZipError("Không phải tệp .xlsx (không đọc được cấu trúc nén).");
  const count = dv.getUint16(eocd + 10, true);
  let at = dv.getUint32(eocd + 16, true);
  const decoder = new TextDecoder("utf-8");
  const entries = new Map<string, ZipEntry>();
  for (let n = 0; n < count; n += 1) {
    if (dv.getUint32(at, true) !== CENTRAL) throw new ZipError("Tệp .xlsx bị hỏng.");
    const method = dv.getUint16(at + 10, true);
    const compressedSize = dv.getUint32(at + 20, true);
    const nameLength = dv.getUint16(at + 28, true);
    const extraLength = dv.getUint16(at + 30, true);
    const commentLength = dv.getUint16(at + 32, true);
    const localOffset = dv.getUint32(at + 42, true);
    const name = decoder.decode(bytes.subarray(at + 46, at + 46 + nameLength));
    entries.set(name, { name, method, compressedSize, localOffset });
    at += 46 + nameLength + extraLength + commentLength;
  }
  return entries;
}

async function inflate(data: Uint8Array): Promise<Uint8Array> {
  if (typeof DecompressionStream === "undefined") {
    throw new ZipError("Trình duyệt này chưa đọc được tệp .xlsx. Hãy dùng Chrome, Edge hoặc Safari bản mới.");
  }
  const source = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(data);
      controller.close();
    },
  });
  const inflated = source.pipeThrough(new DecompressionStream("deflate-raw") as unknown as ReadableWritablePair<Uint8Array, Uint8Array>);
  return new Uint8Array(await new Response(inflated).arrayBuffer());
}

export async function readEntry(bytes: Uint8Array, entry: ZipEntry): Promise<Uint8Array> {
  const dv = view(bytes);
  if (dv.getUint32(entry.localOffset, true) !== LOCAL) throw new ZipError("Tệp .xlsx bị hỏng.");
  const start = entry.localOffset + 30 + dv.getUint16(entry.localOffset + 26, true) + dv.getUint16(entry.localOffset + 28, true);
  const data = bytes.subarray(start, start + entry.compressedSize);
  if (entry.method === 0) return data;
  if (entry.method === 8) return inflate(data);
  throw new ZipError("Tệp .xlsx dùng kiểu nén chưa hỗ trợ.");
}
