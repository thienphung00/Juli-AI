// The few Chrome extension APIs the connector uses, typed by hand so the package
// needs no @types/chrome dependency. Extend only with what the code calls.

declare namespace chrome {
  namespace runtime {
    interface MessageSender {
      tab?: { id?: number; url?: string };
      id?: string;
      origin?: string;
    }
    function sendMessage(message: unknown): Promise<unknown>;
    function getManifest(): { version: string; name: string };
    const id: string;
    const onMessage: {
      addListener(
        callback: (
          message: unknown,
          sender: MessageSender,
          sendResponse: (response?: unknown) => void,
        ) => boolean | void,
      ): void;
    };
    const onInstalled: { addListener(callback: () => void): void };
    const onStartup: { addListener(callback: () => void): void };
  }

  namespace storage {
    const local: {
      get(keys?: string | string[] | null): Promise<Record<string, unknown>>;
      set(items: Record<string, unknown>): Promise<void>;
      remove(keys: string | string[]): Promise<void>;
    };
  }

  namespace alarms {
    interface Alarm {
      name: string;
      scheduledTime: number;
    }
    function create(
      name: string,
      info: { when?: number; delayInMinutes?: number; periodInMinutes?: number },
    ): Promise<void>;
    function get(name: string): Promise<Alarm | undefined>;
    const onAlarm: { addListener(callback: (alarm: Alarm) => void): void };
  }

  namespace tabs {
    interface Tab {
      id?: number;
      url?: string;
    }
    function query(info: { url?: string | string[] }): Promise<Tab[]>;
    function sendMessage(tabId: number, message: unknown): Promise<unknown>;
  }
}
