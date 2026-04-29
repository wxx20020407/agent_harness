import { useState } from "react"
import {
  User,
  Bot,
  Copy,
  Check,
  ChevronDown,
  ChevronRight,
  Terminal,
  FileText,
  Search,
  Brain,
  Cog,
  Loader2,
  CheckCircle2,
  Clock,
} from "lucide-react"
import { cn } from "@/lib/utils"
import { MarkdownRenderer } from "./markdown-renderer"

export function MessageBubble({ message, isLatest, isLoading }) {
  const [copied, setCopied] = useState(false)
  const [thinkingExpanded, setThinkingExpanded] = useState(false)
  const [toolsExpanded, setToolsExpanded] = useState(true)

  const isUser = message.role === "user"

  const copyToClipboard = async () => {
    await navigator.clipboard.writeText(message.content)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div
      className={cn(
        "flex gap-4",
        isUser ? "flex-row-reverse animate-slide-in-right" : "animate-slide-in-left"
      )}
    >
      {/* Avatar */}
      <div
        className={cn(
          "flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border",
          isUser
            ? "bg-primary/10 border-primary/30 text-primary"
            : "bg-secondary border-border text-muted-foreground"
        )}
      >
        {isUser ? <User size={20} /> : <Bot size={20} />}
      </div>

      {/* Content */}
      <div className={cn("flex flex-col gap-2 max-w-[80%]", isUser && "items-end")}>
        {/* Thinking Process */}
        {!isUser && message.thinking && message.thinking.length > 0 && (
          <div
            className={cn(
              "w-full rounded-xl border",
              "bg-[oklch(0.15_0.02_280/0.5)] border-[oklch(0.25_0.03_280/0.5)]"
            )}
          >
            <button
              onClick={() => setThinkingExpanded(!thinkingExpanded)}
              className="flex items-center gap-2 w-full p-3 text-left"
            >
              {thinkingExpanded ? (
                <ChevronDown size={16} className="text-[oklch(0.6_0.15_280)]" />
              ) : (
                <ChevronRight size={16} className="text-[oklch(0.6_0.15_280)]" />
              )}
              <Brain size={16} className="text-[oklch(0.6_0.15_280)]" />
              <span className="text-sm font-medium text-[oklch(0.7_0.1_280)]">
                Thinking Process
              </span>
              <span className="text-xs text-muted-foreground ml-auto">
                {message.thinking.length} steps
              </span>
            </button>

            {thinkingExpanded && (
              <div className="px-4 pb-3 space-y-2">
                {message.thinking.map((thought, index) => (
                  <div
                    key={index}
                    className="text-sm text-muted-foreground pl-6 border-l-2 border-[oklch(0.3_0.03_280)]"
                  >
                    {thought}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Tool Calls */}
        {!isUser && message.tools && message.tools.length > 0 && (
          <div
            className={cn(
              "w-full rounded-xl border",
              "bg-secondary/50 border-border"
            )}
          >
            <button
              onClick={() => setToolsExpanded(!toolsExpanded)}
              className="flex items-center gap-2 w-full p-3 text-left"
            >
              {toolsExpanded ? (
                <ChevronDown size={16} className="text-muted-foreground" />
              ) : (
                <ChevronRight size={16} className="text-muted-foreground" />
              )}
              <Cog size={16} className="text-primary" />
              <span className="text-sm font-medium text-foreground">
                Tool Calls
              </span>
              <span className="text-xs text-muted-foreground ml-auto">
                {message.tools.length} tools
              </span>
            </button>

            {toolsExpanded && (
              <div className="px-3 pb-3 space-y-2">
                {message.tools.map((tool, index) => (
                  <ToolCallItem key={index} tool={tool} />
                ))}
              </div>
            )}
          </div>
        )}

        {/* Message Content */}
        <div
          className={cn(
            "rounded-xl px-4 py-3 border",
            isUser
              ? "bg-primary text-primary-foreground border-primary/50"
              : "bg-card text-card-foreground border-border",
            message.error && "bg-destructive/10 border-destructive/30 text-foreground"
          )}
        >
          {!isUser && message.content ? (
            <MarkdownRenderer content={message.content} />
          ) : (
            <p className="whitespace-pre-wrap">{message.content}</p>
          )}

          {/* Typing Indicator */}
          {isLoading && !message.content && (
            <div className="flex items-center gap-1">
              <span
                className="h-2 w-2 rounded-full bg-primary animate-typing"
                style={{ animationDelay: "0ms" }}
              />
              <span
                className="h-2 w-2 rounded-full bg-primary animate-typing"
                style={{ animationDelay: "200ms" }}
              />
              <span
                className="h-2 w-2 rounded-full bg-primary animate-typing"
                style={{ animationDelay: "400ms" }}
              />
            </div>
          )}
        </div>

        {/* Actions */}
        {!isUser && message.content && (
          <div className="flex items-center gap-2">
            <button
              onClick={copyToClipboard}
              className={cn(
                "flex items-center gap-1.5 px-2 py-1 rounded-md text-xs",
                "text-muted-foreground hover:text-foreground",
                "hover:bg-secondary transition-colors"
              )}
            >
              {copied ? (
                <>
                  <Check size={14} className="text-green-500" />
                  <span>Copied!</span>
                </>
              ) : (
                <>
                  <Copy size={14} />
                  <span>Copy</span>
                </>
              )}
            </button>

            <span className="text-xs text-muted-foreground">
              {new Date(message.timestamp).toLocaleTimeString()}
            </span>
          </div>
        )}
      </div>
    </div>
  )
}

function ToolCallItem({ tool }) {
  const [expanded, setExpanded] = useState(false)

  const getToolIcon = (type) => {
    switch (type) {
      case "bash":
        return Terminal
      case "read":
      case "write":
      case "edit":
        return FileText
      case "glob":
      case "grep":
        return Search
      case "subagent":
        return Brain
      case "memory":
        return Brain
      default:
        return Cog
    }
  }

  const getToolStatusColor = (status) => {
    switch (status) {
      case "pending":
        return "text-yellow-500 bg-yellow-500/10 border-yellow-500/30"
      case "running":
        return "text-primary bg-primary/10 border-primary/30"
      case "completed":
        return "text-green-500 bg-green-500/10 border-green-500/30"
      default:
        return "text-muted-foreground bg-secondary border-border"
    }
  }

  const getToolStatusIcon = (status) => {
    switch (status) {
      case "pending":
        return Clock
      case "running":
        return Loader2
      case "completed":
        return CheckCircle2
      default:
        return Cog
    }
  }

  const ToolIcon = getToolIcon(tool.type)
  const StatusIcon = getToolStatusIcon(tool.status)
  const statusColor = getToolStatusColor(tool.status)

  return (
    <div
      className={cn(
        "rounded-lg border p-2",
        statusColor
      )}
    >
      <div
        className="flex items-center gap-2 cursor-pointer"
        onClick={() => setExpanded(!expanded)}
      >
        <ToolIcon size={14} />
        <span className="text-sm font-medium flex-1">{tool.name}</span>
        <StatusIcon
          size={14}
          className={cn(tool.status === "running" && "animate-spin")}
        />
      </div>

      {expanded && (tool.description || tool.command || tool.path || tool.pattern) && (
        <div className="mt-2 pt-2 border-t border-current/20">
          {tool.description && (
            <p className="text-xs opacity-80">{tool.description}</p>
          )}
          {tool.command && (
            <code className="block mt-1 text-xs font-mono bg-background/20 p-1 rounded">
              {tool.command}
            </code>
          )}
          {tool.path && (
            <code className="block mt-1 text-xs font-mono bg-background/20 p-1 rounded">
              {tool.path}
            </code>
          )}
          {tool.pattern && (
            <code className="block mt-1 text-xs font-mono bg-background/20 p-1 rounded">
              {tool.pattern}
            </code>
          )}
        </div>
      )}
    </div>
  )
}
