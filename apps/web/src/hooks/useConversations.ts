import { useEffect, useRef, useState } from 'react';

import { api, UnauthorizedError } from '../api';
import type { Conversation, Message } from '../types';
import { messageFor } from './messageFor';

export function useConversations(token: string | null) {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [conversationId, setConversationId] = useState<string>();
  const [messages, setMessages] = useState<Message[]>([]);
  const [chatBusy, setChatBusy] = useState(false);
  const [chatError, setChatError] = useState<string>();

  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (!token) {
      setConversations([]);
      setConversationId(undefined);
      setMessages([]);
      return;
    }
    api
      .conversations(token)
      .then(setConversations)
      .catch((reason: unknown) => {
        if (reason instanceof UnauthorizedError) return;
        setChatError(messageFor(reason));
      });
  }, [token]);

  useEffect(() => {
    if (!token || !conversationId) {
      setMessages([]);
      return;
    }
    api
      .messages(conversationId, token)
      .then(setMessages)
      .catch((reason: unknown) => {
        if (reason instanceof UnauthorizedError) return;
        setChatError(messageFor(reason));
      });
  }, [conversationId, token]);

  async function createConversation() {
    if (!token) return;
    setChatBusy(true);
    setChatError(undefined);
    try {
      const conversation = await api.createConversation(token);
      setConversations((current) => [conversation, ...current]);
      setConversationId(conversation.id);
      setMessages([]);
    } catch (reason) {
      if (!(reason instanceof UnauthorizedError)) setChatError(messageFor(reason));
    } finally {
      setChatBusy(false);
    }
  }

  async function sendMessage(text: string) {
    if (!token || !conversationId || !text.trim()) return;
    const clean = text.trim();
    setChatError(undefined);

    const userMessage: Message = {
      id: crypto.randomUUID(),
      role: 'user',
      text: clean,
      created_at: new Date().toISOString()
    };
    const assistantId = crypto.randomUUID();
    const pendingAssistant: Message = {
      id: assistantId,
      role: 'assistant',
      text: 'Thinking…',
      created_at: new Date().toISOString()
    };
    setMessages((current) => [...current, userMessage, pendingAssistant]);

    const controller = new AbortController();
    abortRef.current = controller;
    setChatBusy(true);
    try {
      const answer = await api.sendMessage(conversationId, clean, token, controller.signal);
      setMessages((current) =>
        current.map((message) => (message.id === assistantId ? answer : message))
      );
    } catch (reason) {
      if (reason instanceof DOMException && reason.name === 'AbortError') {
        const canceled: Message = {
          id: assistantId,
          role: 'assistant',
          text: 'Canceled.',
          created_at: new Date().toISOString()
        };
        setMessages((current) =>
          current.map((message) => (message.id === assistantId ? canceled : message))
        );
      } else if (!(reason instanceof UnauthorizedError)) {
        setChatError(messageFor(reason));
        setMessages((current) =>
          current.map((message) =>
            message.id === assistantId
              ? { ...message, text: 'Message failed. Try again.' }
              : message
          )
        );
      }
    } finally {
      setChatBusy(false);
      abortRef.current = null;
    }
  }

  function cancelChat() {
    abortRef.current?.abort();
  }

  return {
    conversations,
    conversationId,
    setConversationId,
    messages,
    createConversation,
    sendMessage,
    cancelChat,
    chatBusy,
    chatError,
    setChatError
  };
}
