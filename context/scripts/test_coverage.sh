#!/bin/bash
# test_coverage.sh - Запуск тестов с отчетом о покрытии

set -e

# Цвета для вывода
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${BLUE}🧪 Sounduk API - Test Coverage Report${NC}"
echo "----------------------------------------"

# Проверка Python окружения
if ! command -v python3 &> /dev/null; then
    echo "❌ Python3 не найден. Установи Python 3.9+"
    exit 1
fi

# Активация виртуального окружения
if [ ! -d "venv" ]; then
    echo "❌ Виртуальное окружение не найдено. Запусти run_dev.sh"
    exit 1
fi

source venv/bin/activate

# Проверка pytest и pytest-cov
if ! pip show pytest &> /dev/null; then
    echo "📦 Установка pytest и pytest-cov..."
    pip install pytest pytest-cov
fi

# Запуск тестов с отчетом о покрытии
echo -e "${YELLOW}Запуск тестов...${NC}"
python3 -m pytest test/ \
    --cov=. \
    --cov-report=html \
    --cov-report=term-missing \
    --cov-report=json \
    -v

echo ""
echo -e "${GREEN}✅ Тесты завершены${NC}"
echo "📊 HTML отчет: htmlcov/index.html"
echo ""

# Вывод краткого резюме
if [ -f ".coverage" ]; then
    echo -e "${BLUE}Детальный отчет:${NC}"
    python3 -m pytest test/ --cov=. --cov-report=term-missing | tail -20
fi

# Деактивация виртуального окружения
deactivate
