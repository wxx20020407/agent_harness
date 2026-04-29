"use client"

import { useState, useRef, useEffect, useCallback } from "react"
import { Sidebar } from "@/components/chat/sidebar"
import { ChatArea } from "@/components/chat/chat-area"
import { ConfigModal } from "@/components/chat/config-modal"
import type { Session, Message, Config, Meta } from "@/lib/types"

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:4201"

export default function AgentChat() {
  const [sessions, setSessions] = useState<Session[]>([])
  const [currentSession, setCurrentSession] = useState<Session | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [loading, setLoading] = useState(false)
  const [input, setInput] = useState("")
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const [configOpen, setConfigOpen] = useState(false)
  const [meta, setMeta] = useState<Meta | null>(null)
  const [config, setConfig] = useState<Config>({
    apiUrl: "",
    apiKey: "",
    model: "claude-3-opus",
  })

  const abortControllerRef = useRef<AbortController | null>(null)

  // Fetch sessions on mount
  useEffect(() => {
    fetchSessions()
    fetchMeta()
  }, [])

  const fetchSessions = async () => {
    try {
      const res = await fetch(`${API_URL}/sessions`)
      if (res.ok) {
        const data = await res.json()
        setSessions(data)
      }
    } catch (error) {
      console.error("Failed to fetch sessions:", error)
    }
  }

  const fetchMeta = async () => {
    try {
      const res = await fetch(`${API_URL}/meta`)
      if (res.ok) {
        const data = await res.json()
        setMeta(data)
      }
    } catch (error) {
      console.error("Failed to fetch meta:", error)
    }
  }

  const createSession = async () => {
    try {
      const res = await fetch(`${API_URL}/sessions`, { method: "POST" })
      if (res.ok) {
        const newSession = await res.json()
        setSessions((prev) => [newSession, ...prev])
        setCurrentSession(newSession)
        setMessages([])
      }
    } catch (error) {
      console.error("Failed to create session:", error)
    }
  }

  const deleteSession = async (id: string) => {
    try {
      const res = await fetch(`${API_URL}/sessions/${id}`, { method: "DELETE" })
      if (res.ok) {
        setSessions((prev) => prev.filter((s) => s.id !== id))
        if (currentSession?.id === id) {
          setCurrentSession(null)
          setMessages([])
        }
      }
    } catch (error) {
      console.error("Failed to delete session:", error)
    }
  }

  const selectSession = async (session: Session) => {
    setCurrentSession(session)
    setMessages(session.messages || [])
  }

  const sendMessage = useCallback(async () => {
    if (!input.trim() || !currentSession || loading) return

    const userMessage: Message = {
      id: Date.now().toString(),
      role: "user",
      content: input,
      timestamp: new Date().toISOString(),
    }

    setMessages((prev) => [...prev, userMessage])
    setInput("")
    setLoading(true)

    // Create AI message placeholder
    const aiMessageId = (Date.now() + 1).toString()
    const aiMessage: Message = {
      id: aiMessageId,
      role: "assistant",
      content: "",
      timestamp: new Date().toISOString(),
      thinking: [],
      tools: [],
    }
    setMessages((prev) => [...prev, aiMessage])

    try {
      abortControllerRef.current = new AbortController()

      const res = await fetch(`${API_URL}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sessionId: currentSession.id,
          message: input,
        }),
        signal: abortControllerRef.current.signal,
      })

      if (!res.ok) throw new Error("Failed to send message")

      const reader = res.body?.getReader()
      if (!reader) throw new Error("No reader available")

      const decoder = new TextDecoder()
      let buffer = ""

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split("\n")
        buffer = lines.pop() || ""

        for (const line of lines) {
          if (line.startsWith("data: ")) {
            try {
              const data = JSON.parse(line.slice(6))
              handleSSEEvent(aiMessageId, data)
            } catch {
              // Ignore parsing errors
            }
          }
        }
      }
    } catch (error) {
      if ((error as Error).name !== "AbortError") {
        console.error("Failed to send message:", error)
        setMessages((prev) =>
          prev.map((m) =>
            m.id === aiMessageId
              ? { ...m, content: "Error: Failed to get response", error: true }
              : m
          )
        )
      }
    } finally {
      setLoading(false)
      abortControllerRef.current = null
    }
  }, [input, currentSession, loading])

  const handleSSEEvent = (messageId: string, data: { type: string; content?: string; tool?: string; name?: string; status?: string; agent?: string; description?: string }) => {
    setMessages((prev) =>
      prev.map((m) => {
        if (m.id !== messageId) return m

        switch (data.type) {
          case "text":
            return { ...m, content: m.content + (data.content || "") }
          case "thinking":
            return {
              ...m,
              thinking: [...(m.thinking || []), data.content || ""],
            }
          case "tool":
            const existingToolIndex = m.tools?.findIndex(
              (t) => t.name === data.name && t.status === "pending"
            )
            if (existingToolIndex !== undefined && existingToolIndex >= 0) {
              const newTools = [...(m.tools || [])]
              newTools[existingToolIndex] = {
                ...newTools[existingToolIndex],
                status: data.status || "pending",
              }
              return { ...m, tools: newTools }
            }
            return {
              ...m,
              tools: [
                ...(m.tools || []),
                {
                  type: data.tool || "unknown",
                  name: data.name || "Unknown Tool",
                  status: data.status || "pending",
                },
              ],
            }
          case "subagent":
            return {
              ...m,
              tools: [
                ...(m.tools || []),
                {
                  type: "subagent",
                  name: data.agent || "Subagent",
                  description: data.description,
                  status: "running",
                },
              ],
            }
          case "error":
            return { ...m, content: m.content + `\n\nError: ${data.content}`, error: true }
          case "done":
            return { ...m, completed: true }
          default:
            return m
        }
      })
    )
  }

  const stopGeneration = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort()
      setLoading(false)
    }
  }

  const refreshDocs = async () => {
    try {
      await fetch(`${API_URL}/docs/convert`, { method: "POST" })
    } catch (error) {
      console.error("Failed to refresh docs:", error)
    }
  }

  const consolidateMemory = async () => {
    try {
      await fetch(`${API_URL}/memory/consolidate`, { method: "POST" })
    } catch (error) {
      console.error("Failed to consolidate memory:", error)
    }
  }

  const saveConfig = async (newConfig: Config) => {
    try {
      await fetch(`${API_URL}/config`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(newConfig),
      })
      setConfig(newConfig)
      setConfigOpen(false)
    } catch (error) {
      console.error("Failed to save config:", error)
    }
  }

  const uploadFile = async (file: File) => {
    const formData = new FormData()
    formData.append("file", file)

    try {
      const res = await fetch(`${API_URL}/upload`, {
        method: "POST",
        body: formData,
      })
      if (res.ok) {
        const data = await res.json()
        return data.url
      }
    } catch (error) {
      console.error("Failed to upload file:", error)
    }
    return null
  }

  return (
    <div className="flex h-screen overflow-hidden bg-background">
      {/* Sidebar */}
      <Sidebar
        sessions={sessions}
        currentSession={currentSession}
        onSelectSession={selectSession}
        onCreateSession={createSession}
        onDeleteSession={deleteSession}
        isOpen={sidebarOpen}
        onToggle={() => setSidebarOpen(!sidebarOpen)}
        meta={meta}
      />

      {/* Main Chat Area */}
      <ChatArea
        currentSession={currentSession}
        messages={messages}
        loading={loading}
        input={input}
        onInputChange={setInput}
        onSendMessage={sendMessage}
        onStopGeneration={stopGeneration}
        onOpenConfig={() => setConfigOpen(true)}
        onRefreshDocs={refreshDocs}
        onConsolidateMemory={consolidateMemory}
        onUploadFile={uploadFile}
        sidebarOpen={sidebarOpen}
        onToggleSidebar={() => setSidebarOpen(!sidebarOpen)}
      />

      {/* Config Modal */}
      <ConfigModal
        isOpen={configOpen}
        onClose={() => setConfigOpen(false)}
        config={config}
        onSave={saveConfig}
      />
    </div>
  )
}
