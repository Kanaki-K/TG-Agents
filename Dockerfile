FROM node:24-slim

RUN npm install -g @anthropic-ai/claude-code

# git нужен, чтобы вести версии и работать с GitHub прямо из контейнера
RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

ENV HOME=/claude-home
RUN mkdir -p /claude-home

WORKDIR /workspace
CMD ["claude"]