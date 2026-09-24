import { useCallback, useEffect, useState } from "react";
import { api, RecordItem } from "./api";
type History = { messages: RecordItem[]; has_more: boolean };
export function useHistory(id: string | null, revision: string) {
  const [data, setData] = useState<History>({ messages: [], has_more: false });
  const [error, setError] = useState("");
  useEffect(() => {
    if (!id) return;
    let live = true;
    api<History>("/conversations/" + id + "/messages")
      .then((next) => {
        if (live) {
          setData(next);
          setError("");
        }
      })
      .catch((e) => {
        if (live) setError(e.message);
      });
    return () => {
      live = false;
    };
  }, [id, revision]);
  const messages = id
    ? data.messages.filter((m) => m.conversation_id === id)
    : [];
  const loadOlder = useCallback(async () => {
    if (!id) return;
    try {
      const next = await api<History>(
        "/conversations/" + id + "/messages?offset=" + messages.length,
      );
      setData((previous) => ({
        messages: [
          ...next.messages,
          ...previous.messages.filter(
            (m) => !next.messages.some((n) => n.id === m.id),
          ),
        ],
        has_more: next.has_more,
      }));
    } catch (e) {
      setError((e as Error).message);
    }
  }, [id, messages.length]);
  return { messages, hasMore: !!id && data.has_more, error, loadOlder };
}
