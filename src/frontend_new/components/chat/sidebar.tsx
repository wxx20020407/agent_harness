"use client"

import { useState } from "react"
import {
  Plus,
  Trash2,
  MessageSquare,
  ChevronLeft,
  ChevronRight,
  Cpu,
  FileText,
  Zap,
} from "lucide-react"
import { cn } from "@/lib/utils"
import type { Session, Meta } from "@/lib/types"

interface SidebarProps {
  sessions: Session[]
  currentSession: Session | null
  onSelectSession: (session: Session) => void
  onCreateSession: () => void
  onDeleteSession: (id: string) => void
  isOpen: boolean
  onToggle: () => void
  meta: Meta | null
}

export function Sidebar({
  sessions,
  currentSession,
  onSelectSession,
  onCreateSession,
  onDeleteSession,
  isOpen,
  onToggle,
  meta,
}: SidebarProps) {
  const [hoveredSession, setHoveredSession] = useState<string | null>(null)

  return (
    <>
      {/* Collapse/Expand Button */}
      <button
        onClick={onToggle}
        className={cn(
          "fixed top-4 z-50 flex h-8 w-8 items-center justify-center rounded-md",
          "bg-card border border-border text-muted-foreground",
          "transition-all duration-300 hover:bg-secondary hover:text-foreground",
          isOpen ? "left-[244px]" : "left-4"
        )}
      >
        {isOpen ? <ChevronLeft size={16} /> : <ChevronRight size={16} />}
      </button>

      {/* Sidebar */}
      <aside
        className={cn(
          "flex h-full flex-col bg-sidebar border-r border-sidebar-border",
          "transition-all duration-300 ease-in-out",
          isOpen ? "w-[260px]" : "w-0 overflow-hidden"
        )}
      >
        {/* Header */}
        <div className="flex flex-col gap-4 p-4 border-b border-sidebar-border">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10 border border-primary/30">
              <Cpu className="h-5 w-5 text-primary animate-pulse-glow" />
            </div>
            <div>
              <h1 className="font-semibold text-sidebar-foreground">
                {meta?.teamName || "AI Agent"}
              </h1>
              <p className="text-xs text-muted-foreground">Neural Interface</p>
            </div>
          </div>

          <button
            onClick={onCreateSession}
            className={cn(
              "flex items-center justify-center gap-2 w-full py-2.5 px-4 rounded-lg",
              "bg-primary/10 border border-primary/30 text-primary",
              "transition-all duration-200 hover:bg-primary/20 hover:border-primary/50",
              "hover:shadow-[0_0_15px_rgba(59,130,246,0.3)]"
            )}
          >
            <Plus size={18} />
            <span className="font-medium">New Session</span>
          </button>
        </div>

        {/* Sessions List */}
        <div className="flex-1 overflow-y-auto p-2">
          <div className="space-y-1">
            {sessions.map((session, index) => (
              <div
                key={session.id}
                className={cn(
                  "group relative flex items-center gap-3 p-3 rounded-lg cursor-pointer",
                  "transition-all duration-200",
                  "animate-fade-in",
                  currentSession?.id === session.id
                    ? "bg-sidebar-accent border border-primary/30 shadow-[0_0_10px_rgba(59,130,246,0.15)]"
                    : "hover:bg-sidebar-accent/50 border border-transparent"
                )}
                style={{ animationDelay: `${index * 50}ms` }}
                onClick={() => onSelectSession(session)}
                onMouseEnter={() => setHoveredSession(session.id)}
                onMouseLeave={() => setHoveredSession(null)}
              >
                <div
                  className={cn(
                    "flex h-8 w-8 items-center justify-center rounded-md",
                    currentSession?.id === session.id
                      ? "bg-primary/20 text-primary"
                      : "bg-secondary text-muted-foreground"
                  )}
                >
                  <MessageSquare size={16} />
                </div>

                <div className="flex-1 min-w-0">
                  <p
                    className={cn(
                      "truncate text-sm font-medium",
                      currentSession?.id === session.id
                        ? "text-sidebar-foreground"
                        : "text-sidebar-foreground/70"
                    )}
                  >
                    {session.title || "New Conversation"}
                  </p>
                  <p className="text-xs text-muted-foreground truncate">
                    {new Date(session.updatedAt).toLocaleDateString()}
                  </p>
                </div>

                {session.unread && (
                  <div className="absolute right-12 top-1/2 -translate-y-1/2 h-2 w-2 rounded-full bg-primary animate-pulse-glow" />
                )}

                {hoveredSession === session.id && (
                  <button
                    onClick={(e) => {
                      e.stopPropagation()
                      onDeleteSession(session.id)
                    }}
                    className={cn(
                      "absolute right-2 p-1.5 rounded-md",
                      "bg-destructive/10 text-destructive",
                      "transition-all duration-200 hover:bg-destructive/20",
                      "opacity-0 group-hover:opacity-100"
                    )}
                  >
                    <Trash2 size={14} />
                  </button>
                )}
              </div>
            ))}

            {sessions.length === 0 && (
              <div className="flex flex-col items-center justify-center py-12 text-center">
                <div className="h-12 w-12 rounded-full bg-secondary flex items-center justify-center mb-3">
                  <MessageSquare className="h-6 w-6 text-muted-foreground" />
                </div>
                <p className="text-sm text-muted-foreground">No sessions yet</p>
                <p className="text-xs text-muted-foreground/70 mt-1">
                  Create a new session to start
                </p>
              </div>
            )}
          </div>
        </div>

        {/* Footer - Meta Info */}
        {meta && (
          <div className="p-4 border-t border-sidebar-border">
            <div className="space-y-2">
              {meta.skills.length > 0 && (
                <div className="flex items-center gap-2 text-xs text-muted-foreground">
                  <Zap size={12} className="text-primary" />
                  <span>{meta.skills.length} skills available</span>
                </div>
              )}
              {meta.kbFiles.length > 0 && (
                <div className="flex items-center gap-2 text-xs text-muted-foreground">
                  <FileText size={12} className="text-primary" />
                  <span>{meta.kbFiles.length} knowledge files</span>
                </div>
              )}
            </div>
          </div>
        )}
      </aside>
    </>
  )
}
