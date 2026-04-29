import { useState, useEffect } from "react"
import { X, Server, Key, Cpu, Save } from "lucide-react"
import { cn } from "@/lib/utils"

const MODELS = [
  { value: "claude-3-opus", label: "Claude 3 Opus" },
  { value: "claude-3-sonnet", label: "Claude 3 Sonnet" },
  { value: "claude-3-haiku", label: "Claude 3 Haiku" },
  { value: "gpt-4o", label: "GPT-4o" },
  { value: "gpt-4-turbo", label: "GPT-4 Turbo" },
  { value: "gpt-3.5-turbo", label: "GPT-3.5 Turbo" },
  { value: "gemini-pro", label: "Gemini Pro" },
  { value: "gemini-ultra", label: "Gemini Ultra" },
]

export function ConfigModal({ isOpen, onClose, config, onSave }) {
  const [formData, setFormData] = useState(config)

  useEffect(() => {
    setFormData(config)
  }, [config])

  useEffect(() => {
    const handleEscape = (e) => {
      if (e.key === "Escape") onClose()
    }

    if (isOpen) {
      document.addEventListener("keydown", handleEscape)
      document.body.style.overflow = "hidden"
    }

    return () => {
      document.removeEventListener("keydown", handleEscape)
      document.body.style.overflow = ""
    }
  }, [isOpen, onClose])

  if (!isOpen) return null

  const handleSubmit = (e) => {
    e.preventDefault()
    onSave(formData)
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-background/80 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* Modal */}
      <div
        className={cn(
          "relative w-full max-w-md mx-4",
          "bg-card border border-border rounded-2xl",
          "shadow-[0_0_50px_rgba(59,130,246,0.15)]",
          "animate-fade-in"
        )}
      >
        {/* Header */}
        <div className="flex items-center justify-between p-6 border-b border-border">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary/10 border border-primary/30">
              <Cpu className="h-5 w-5 text-primary" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-foreground">
                Configuration
              </h2>
              <p className="text-xs text-muted-foreground">
                LLM API Settings
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className={cn(
              "p-2 rounded-lg",
              "text-muted-foreground hover:text-foreground",
              "hover:bg-secondary transition-colors"
            )}
          >
            <X size={20} />
          </button>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="p-6 space-y-5">
          {/* API URL */}
          <div className="space-y-2">
            <label className="flex items-center gap-2 text-sm font-medium text-foreground">
              <Server size={16} className="text-primary" />
              API URL
            </label>
            <input
              type="url"
              value={formData.apiUrl}
              onChange={(e) =>
                setFormData({ ...formData, apiUrl: e.target.value })
              }
              placeholder="https://api.openai.com/v1"
              className={cn(
                "w-full px-4 py-3 rounded-lg",
                "bg-input border border-border",
                "text-foreground placeholder:text-muted-foreground",
                "transition-all duration-200",
                "focus:outline-none focus:border-primary/50",
                "focus:shadow-[0_0_15px_rgba(59,130,246,0.2)]"
              )}
            />
          </div>

          {/* API Key */}
          <div className="space-y-2">
            <label className="flex items-center gap-2 text-sm font-medium text-foreground">
              <Key size={16} className="text-primary" />
              API Key
            </label>
            <input
              type="password"
              value={formData.apiKey}
              onChange={(e) =>
                setFormData({ ...formData, apiKey: e.target.value })
              }
              placeholder="sk-..."
              className={cn(
                "w-full px-4 py-3 rounded-lg",
                "bg-input border border-border",
                "text-foreground placeholder:text-muted-foreground",
                "transition-all duration-200",
                "focus:outline-none focus:border-primary/50",
                "focus:shadow-[0_0_15px_rgba(59,130,246,0.2)]"
              )}
            />
          </div>

          {/* Model Selection */}
          <div className="space-y-2">
            <label className="flex items-center gap-2 text-sm font-medium text-foreground">
              <Cpu size={16} className="text-primary" />
              Model
            </label>
            <select
              value={formData.model}
              onChange={(e) =>
                setFormData({ ...formData, model: e.target.value })
              }
              className={cn(
                "w-full px-4 py-3 rounded-lg",
                "bg-input border border-border",
                "text-foreground",
                "transition-all duration-200",
                "focus:outline-none focus:border-primary/50",
                "focus:shadow-[0_0_15px_rgba(59,130,246,0.2)]",
                "cursor-pointer appearance-none",
                "bg-[url('data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMTYiIGhlaWdodD0iMTYiIHZpZXdCb3g9IjAgMCAxNiAxNiIgZmlsbD0ibm9uZSIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48cGF0aCBkPSJNNCA2TDggMTBMMTIgNiIgc3Ryb2tlPSIjNjQ3NDhCIiBzdHJva2Utd2lkdGg9IjIiIHN0cm9rZS1saW5lY2FwPSJyb3VuZCIgc3Ryb2tlLWxpbmVqb2luPSJyb3VuZCIvPjwvc3ZnPg==')]",
                "bg-[position:right_1rem_center]",
                "bg-no-repeat"
              )}
            >
              {MODELS.map((model) => (
                <option
                  key={model.value}
                  value={model.value}
                  className="bg-card text-foreground"
                >
                  {model.label}
                </option>
              ))}
            </select>
          </div>

          {/* Submit */}
          <button
            type="submit"
            className={cn(
              "w-full flex items-center justify-center gap-2 py-3 px-4 rounded-lg",
              "bg-primary text-primary-foreground font-medium",
              "transition-all duration-200",
              "hover:bg-primary/90",
              "hover:shadow-[0_0_20px_rgba(59,130,246,0.4)]"
            )}
          >
            <Save size={18} />
            Save Configuration
          </button>
        </form>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-border">
          <p className="text-xs text-muted-foreground text-center">
            Your API key is stored securely and never shared.
          </p>
        </div>
      </div>
    </div>
  )
}
