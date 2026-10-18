#!/bin/bash
set -e

# Go to Gym16_bot directory
cd "$(dirname "$0")"

# Check if cloudflared binary exists, if not - download it
if [ ! -f "./cloudflared" ]; then
    echo "📦 Файл cloudflared не найден. Скачиваем официальный бинарник Cloudflare..."
    curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-arm64.tgz | tar -xz
    chmod +x cloudflared
    echo "✅ cloudflared успешно установлен!"
fi

echo "🚀 Запуск постоянного Cloudflare туннеля (HTTP/2, IPv4)..."
./cloudflared tunnel --protocol http2 --edge-ip-version 4 --url http://localhost:8000
