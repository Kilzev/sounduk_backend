#!/bin/bash
# run_dev.sh - Запуск dev-сервера Sounduk API

set -e

# Цвета для вывода
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}🎵 Sounduk API - Development Server${NC}"
echo "-----------------------------------"

# Проверка Python окружения
if ! command -v python3 &> /dev/null; then
    echo "❌ Python3 не найден. Установи Python 3.9+"
    exit 1
fi

# Проверка виртуального окружения
if [ ! -d "venv" ]; then
    echo "⚠️  Виртуальное окружение не найдено. Создаю..."
    python3 -m venv venv
fi

# Активация виртуального окружения
source venv/bin/activate

# Установка зависимостей (если требуется)
if [ ! -f "venv/pyvenv.cfg" ]; then
    echo "📦 Установка зависимостей..."
    pip install -r requirements.txt
fi

# Проверка .env файла
if [ ! -f ".env" ]; then
    echo "⚠️  Файл .env не найден!"
    echo "   Создай .env с необходимыми переменными окружения"
    echo "   Пример:"
    echo "   - SMTP_HOST=..."
    echo "   - AWS_ACCESS_KEY=..."
    echo "   - YOOKASSA_SHOP_ID=..."
    exit 1
fi

# Запуск сервера
echo -e "${GREEN}✅ Запуск сервера на http://localhost:8000${NC}"
echo "   📚 Документация: http://localhost:8000/docs"
echo "   ReDoc: http://localhost:8000/redoc"
echo "-----------------------------------"

python3 -m uvicorn main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --reload \
    --reload-dirs=. \
    --log-level info

# Деактивация виртуального окружения
deactivate
