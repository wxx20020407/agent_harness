import { useRef, useEffect } from "react"
import {
  Settings,
  RefreshCw,
  Brain,
  Send,
  Paperclip,
  Square,
  Menu,
  Sparkles,
} from "lucide-react"
import { cn } from "@/lib/utils"
import { MessageBubble } from "./message-bubble"

export function ChatArea({
  currentSession,
  messages,
  loading,
  input,
  onInputChange,
  onSendMessage,
  onStopGeneration,
  onOpenConfig,
  onRefreshDocs,
  onConsolidateMemory,
  onUploadFile,
  sidebarOpen,
  onToggleSidebar,
}) {
  const messagesEndRef = useRef(null)
  const textareaRef = useRef(null)
  const fileInputRef = useRef(null)

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages])

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto"
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 200)}px`
    }
  }, [input])

  const handleKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault()
      onSendMessage()
    }
  }

  const handleFileSelect = async (e) => {
    const file = e.target.files?.[0]
    if (file) {
      const url = await onUploadFile(file)
      if (url) {
        onInputChange(input + ` [Attached: ${file.name}](${url})`)
      }
    }
    if (fileInputRef.current) {
      fileInputRef.current.value = ""
    }
  }

  return (
    <main className="flex flex-1 flex-col h-full overflow-hidden">
      {/* Header */}
      <header className="flex items-center justify-between px-6 py-4 border-b border-border bg-card/50 backdrop-blur-sm">
        <div className="flex items-center gap-4">
          {!sidebarOpen && (
            <button
              onClick={onToggleSidebar}
              className="p-2 rounded-lg hover:bg-secondary transition-colors"
            >
              <Menu size={20} className="text-muted-foreground" />
            </button>
          )}
          <div className="flex items-center gap-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary/10 border border-primary/30">
              <Sparkles className="h-4 w-4 text-primary" />
            </div>
            <div>
              <h2 className="font-semibold text-foreground">
                {currentSession?.title || "Select a Session"}
              </h2>
              {currentSession && (
                <p className="text-xs text-muted-foreground">
                  Session ID: {currentSession.id.slice(0, 8)}...
                </p>
              )}
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={onRefreshDocs}
            className={cn(
              "flex items-center gap-2 px-3 py-2 rounded-lg",
              "bg-secondary/50 border border-border",
              "text-sm text-muted-foreground",
              "transition-all duration-200 hover:bg-secondary hover:text-foreground"
            )}
            title="Refresh Documents"
          >
            <RefreshCw size={16} />
            <span className="hidden sm:inline">Refresh Docs</span>
          </button>

          <button
            onClick={onConsolidateMemory}
            className={cn(
              "flex items-center gap-2 px-3 py-2 rounded-lg",
              "bg-secondary/50 border border-border",
              "text-sm text-muted-foreground",
              "transition-all duration-200 hover:bg-secondary hover:text-foreground"
            )}
            title="Consolidate Memory"
          >
            <Brain size={16} />
            <span className="hidden sm:inline">Memory</span>
          </button>

          <button
            onClick={onOpenConfig}
            className={cn(
              "flex items-center gap-2 px-3 py-2 rounded-lg",
              "bg-secondary/50 border border-border",
              "text-sm text-muted-foreground",
              "transition-all duration-200 hover:bg-secondary hover:text-foreground"
            )}
            title="Settings"
          >
            <Settings size={16} />
          </button>
        </div>
      </header>

      {/* Messages Area */}
      <div className="flex-1 overflow-y-auto px-6 py-4">
        {!currentSession ? (
          <div className="flex flex-col items-center justify-center h-full text-center">
            <div className="relative">
              <div className="h-20 w-20 rounded-2xl bg-primary/10 border border-primary/30 flex items-center justify-center mb-6 animate-pulse-glow">
                <Sparkles className="h-10 w-10 text-primary" />
              </div>
              <div className="absolute -top-1 -right-1 h-4 w-4 rounded-full bg-green-500 border-2 border-background animate-pulse" />
            </div>
            <h3 className="text-xl font-semibold text-foreground mb-2">
              AI Agent Ready
            </h3>
            <p className="text-muted-foreground max-w-md">
              Select an existing session or create a new one to start
              interacting with the AI agent.
            </p>
          </div>
        ) : messages.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-center">
            <div className="h-16 w-16 rounded-xl bg-secondary border border-border flex items-center justify-center mb-4">
              <Sparkles className="h-8 w-8 text-muted-foreground" />
            </div>
            <h3 className="text-lg font-medium text-foreground mb-2">
              Start a Conversation
            </h3>
            <p className="text-muted-foreground max-w-md">
              Type a message below to begin chatting with the AI agent.
            </p>
          </div>
        ) : (
          <div className="space-y-6 max-w-4xl mx-auto">
            {messages.map((message, index) => (
              <MessageBubble
                key={message.id}
                message={message}
                isLatest={index === messages.length - 1}
                isLoading={loading && index === messages.length - 1}
              />
            ))}
            <div ref={messagesEndRef} />
          </div>
        )}
      </div>

      {/* Input Area */}
      {currentSession && (
        <div className="px-6 py-4 border-t border-border bg-card/50 backdrop-blur-sm">
          <div className="max-w-4xl mx-auto">
            <div
              className={cn(
                "flex items-end gap-3 p-3 rounded-xl",
                "bg-input border border-border",
                "transition-all duration-200",
                "focus-within:border-primary/50 focus-within:shadow-[0_0_15px_rgba(59,130,246,0.2)]"
              )}
            >
              <input
                type="file"
                ref={fileInputRef}
                onChange={handleFileSelect}
                className="hidden"
              />

              <button
                onClick={() => fileInputRef.current?.click()}
                className={cn(
                  "p-2 rounded-lg",
                  "text-muted-foreground hover:text-foreground",
                  "hover:bg-secondary transition-colors"
                )}
                title="Attach file"
              >
                <Paperclip size={20} />
              </button>

              <textarea
                ref={textareaRef}
                value={input}
                onChange={(e) => onInputChange(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Type your message..."
                rows={1}
                className={cn(
                  "flex-1 bg-transparent resize-none",
                  "text-foreground placeholder:text-muted-foreground",
                  "focus:outline-none",
                  "min-h-[40px] max-h-[200px]"
                )}
                disabled={loading}
              />

              {loading ? (
                <button
                  onClick={onStopGeneration}
                  className={cn(
                    "p-2.5 rounded-lg",
                    "bg-destructive text-destructive-foreground",
                    "transition-all duration-200 hover:bg-destructive/90"
                  )}
                  title="Stop generation"
                >
                  <Square size={18} />
                </button>
              ) : (
                <button
                  onClick={onSendMessage}
                  disabled={!input.trim()}
                  className={cn(
                    "p-2.5 rounded-lg",
                    "bg-primary text-primary-foreground",
                    "transition-all duration-200",
                    input.trim()
                      ? "hover:bg-primary/90 hover:shadow-[0_0_15px_rgba(59,130,246,0.4)]"
                      : "opacity-50 cursor-not-allowed"
                  )}
                  title="Send message"
                >
                  <Send size={18} />
                </button>
              )}
            </div>

            <p className="text-xs text-muted-foreground text-center mt-3">
              Press Enter to send, Shift+Enter for new line
            </p>
          </div>
        </div>
      )}
    </main>
  )
}
