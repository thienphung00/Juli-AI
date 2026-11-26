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
    const onInstalled: { addListener(callback: (details: { reason: string; previousVersion?: string }) => void): void };
    const onStartup: { addListener(callback: () => void): void };
  }

  namespace permissions {
    function request(permissions: { origins?: string[] }): Promise<boolean>;
    function contains(permissions: { origins?: string[] }): Promise<boolean>;
    const onAdded: { addListener(callback: () => void): void };
  }

  namespace scripting {
    interface InjectionResult<T> {
      result?: T;
    }
    interface RegisteredContentScript {
      id: string;
      matches: string[];
      js: string[];
      runAt?: "document_start" | "document_end" | "document_idle";
      persistAcrossSessions?: boolean;
    }
    function registerContentScripts(scripts: RegisteredContentScript[]): Promise<void>;
    function getRegisteredContentScripts(filter?: { ids?: string[] }): Promise<{ id: string }[]>;
    function executeScript<T>(injection: {
      target: { tabId: number };
      world?: "ISOLATED" | "MAIN";
      files?: string[];
      func?: () => T;
    }): Promise<InjectionResult<T>[]>;
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
    function clear(name: string): Promise<boolean>;
    function clearAll(): Promise<boolean>;
    const onAlarm: { addListener(callback: (alarm: Alarm) => void): void };
  }

  namespace tabs {
    interface Tab {
      id?: number;
      url?: string;
      discarded?: boolean;
    }
    function update(tabId: number, props: { autoDiscardable?: boolean }): Promise<Tab>;
    function query(info: { url?: string | string[] }): Promise<Tab[]>;
    function sendMessage(tabId: number, message: unknown): Promise<unknown>;
    function create(info: { url: string; active?: boolean }): Promise<Tab>;
    function remove(tabId: number): Promise<void>;
    function get(tabId: number): Promise<Tab>;
    const onRemoved: { addListener(callback: (tabId: number) => void): void };
    /** 0.3.28: `changeInfo.url` is set when a tab's address changes (host permission on that URL). */
    const onUpdated: { addListener(callback: (tabId: number, changeInfo: { url?: string }) => void): void } | undefined;
  }
}
