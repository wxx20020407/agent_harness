export interface Session {
  id: string
  title: string
  createdAt: string
  updatedAt: string
  unread?: boolean
  messages?: Message[]
}

export interface Message {
  id: string
  role: "user" | "assistant"
  content: string
  timestamp: string
  thinking?: string[]
  tools?: Tool[]
  error?: boolean
  completed?: boolean
}

export interface Tool {
  type: string
  name: string
  status: "pending" | "running" | "completed"
  description?: string
  command?: string
  path?: string
  pattern?: string
}

export interface Config {
  apiUrl: string
  apiKey: string
  model: string
}

export interface Meta {
  skills: string[]
  kbFiles: string[]
  teamName?: string
}
