"use client"

import { useState } from "react"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter"
import { oneDark } from "react-syntax-highlighter/dist/esm/styles/prism"
import { Copy, Check } from "lucide-react"
import { cn } from "@/lib/utils"

interface MarkdownRendererProps {
  content: string
}

export function MarkdownRenderer({ content }: MarkdownRendererProps) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        code({ className, children, ...props }) {
          const match = /language-(\w+)/.exec(className || "")
          const codeString = String(children).replace(/\n$/, "")
          
          if (match) {
            return (
              <CodeBlock language={match[1]} code={codeString} />
            )
          }
          
          return (
            <code
              className={cn(
                "bg-secondary px-1.5 py-0.5 rounded text-sm font-mono",
                "text-primary"
              )}
              {...props}
            >
              {children}
            </code>
          )
        },
        pre({ children }) {
          return <>{children}</>
        },
        p({ children }) {
          return <p className="mb-3 last:mb-0 leading-relaxed">{children}</p>
        },
        h1({ children }) {
          return (
            <h1 className="text-2xl font-bold mb-4 mt-6 first:mt-0 text-foreground">
              {children}
            </h1>
          )
        },
        h2({ children }) {
          return (
            <h2 className="text-xl font-semibold mb-3 mt-5 first:mt-0 text-foreground">
              {children}
            </h2>
          )
        },
        h3({ children }) {
          return (
            <h3 className="text-lg font-semibold mb-2 mt-4 first:mt-0 text-foreground">
              {children}
            </h3>
          )
        },
        ul({ children }) {
          return (
            <ul className="list-disc list-inside mb-3 space-y-1 ml-2">
              {children}
            </ul>
          )
        },
        ol({ children }) {
          return (
            <ol className="list-decimal list-inside mb-3 space-y-1 ml-2">
              {children}
            </ol>
          )
        },
        li({ children }) {
          return <li className="leading-relaxed">{children}</li>
        },
        a({ href, children }) {
          return (
            <a
              href={href}
              target="_blank"
              rel="noopener noreferrer"
              className={cn(
                "text-primary hover:text-primary/80",
                "underline underline-offset-2",
                "transition-colors"
              )}
            >
              {children}
            </a>
          )
        },
        blockquote({ children }) {
          return (
            <blockquote
              className={cn(
                "border-l-4 border-primary/50 pl-4 py-1 my-3",
                "text-muted-foreground italic"
              )}
            >
              {children}
            </blockquote>
          )
        },
        table({ children }) {
          return (
            <div className="overflow-x-auto my-4">
              <table className="min-w-full border border-border rounded-lg overflow-hidden">
                {children}
              </table>
            </div>
          )
        },
        thead({ children }) {
          return <thead className="bg-secondary">{children}</thead>
        },
        tbody({ children }) {
          return <tbody className="divide-y divide-border">{children}</tbody>
        },
        tr({ children }) {
          return (
            <tr className="hover:bg-secondary/50 transition-colors">
              {children}
            </tr>
          )
        },
        th({ children }) {
          return (
            <th className="px-4 py-2 text-left text-sm font-semibold text-foreground">
              {children}
            </th>
          )
        },
        td({ children }) {
          return (
            <td className="px-4 py-2 text-sm text-foreground">{children}</td>
          )
        },
        hr() {
          return <hr className="my-6 border-border" />
        },
        strong({ children }) {
          return <strong className="font-semibold text-foreground">{children}</strong>
        },
        em({ children }) {
          return <em className="italic">{children}</em>
        },
      }}
    >
      {content}
    </ReactMarkdown>
  )
}

function CodeBlock({ language, code }: { language: string; code: string }) {
  const [copied, setCopied] = useState(false)

  const copyToClipboard = async () => {
    await navigator.clipboard.writeText(code)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className="relative my-4 rounded-lg overflow-hidden border border-border">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2 bg-[oklch(0.08_0.01_250)] border-b border-border">
        <span className="text-xs font-medium text-muted-foreground uppercase">
          {language}
        </span>
        <button
          onClick={copyToClipboard}
          className={cn(
            "flex items-center gap-1.5 px-2 py-1 rounded text-xs",
            "text-muted-foreground hover:text-foreground",
            "hover:bg-secondary transition-colors"
          )}
        >
          {copied ? (
            <>
              <Check size={12} className="text-green-500" />
              <span>Copied!</span>
            </>
          ) : (
            <>
              <Copy size={12} />
              <span>Copy</span>
            </>
          )}
        </button>
      </div>

      {/* Code */}
      <SyntaxHighlighter
        style={oneDark}
        language={language}
        PreTag="div"
        customStyle={{
          margin: 0,
          padding: "1rem",
          background: "oklch(0.06 0.01 250)",
          fontSize: "0.875rem",
        }}
        codeTagProps={{
          style: {
            fontFamily: "var(--font-mono)",
          },
        }}
      >
        {code}
      </SyntaxHighlighter>
    </div>
  )
}
