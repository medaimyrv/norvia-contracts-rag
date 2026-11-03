import type { ChatEvent } from "./types";

/**
 * Lector SSE incremental. EventSource solo admite GET y la pregunta no debe ir en la URL
 * (acabaría en logs, S4), así que se usa POST con fetch y se parsea el stream a mano [D9].
 * Los bloques llegan troceados de forma arbitraria: se acumula hasta ver "\n\n".
 */
export class SSEParser {
  private buffer = "";

  feed(chunk: string): ChatEvent[] {
    this.buffer += chunk;
    const events: ChatEvent[] = [];
    let end: number;
    while ((end = this.buffer.indexOf("\n\n")) !== -1) {
      const block = this.buffer.slice(0, end);
      this.buffer = this.buffer.slice(end + 2);
      let name = "message";
      let data = "";
      for (const line of block.split("\n")) {
        if (line.startsWith("event: ")) name = line.slice(7);
        else if (line.startsWith("data: ")) data += line.slice(6);
      }
      if (data) events.push({ event: name, data: JSON.parse(data) } as ChatEvent);
    }
    return events;
  }
}
