variable "TAG" {
  default = "latest"
}

variable "REGISTRY" {
  default = "ghcr.io/kubemind"
}

group "default" {
  targets = ["backend", "frontend", "ml-services", "ai-engine", "agent"]
}

target "backend" {
  dockerfile = "backend/Dockerfile"
  context   = "backend"
  tags      = ["${REGISTRY}/backend:${TAG}"]
}

target "frontend" {
  dockerfile = "frontend/Dockerfile"
  context   = "frontend"
  tags      = ["${REGISTRY}/frontend:${TAG}"]
  args      = {
    NEXT_PUBLIC_API_URL = "http://localhost:8000"
  }
}

target "ml-services" {
  dockerfile = "ml-services/Dockerfile"
  context   = "ml-services"
  tags      = ["${REGISTRY}/ml-services:${TAG}"]
}

target "ai-engine" {
  dockerfile = "ai-engine/Dockerfile"
  context   = "ai-engine"
  tags      = ["${REGISTRY}/ai-engine:${TAG}"]
}

target "agent" {
  dockerfile = "agent/Dockerfile"
  context   = "agent"
  tags      = ["${REGISTRY}/agent:${TAG}"]
}
