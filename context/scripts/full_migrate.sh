#!/bin/bash
# full_migrate.sh - Полный цикл миграций (когда Alembic будет добавлен)

set -e

# Цвета для вывода
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}🔄 Sounduk API - Full Migration Cycle${NC}"
echo "--------------------------------------"

# Проверка наличия alembic
if [ ! -d "alembic" ]; then
    echo -e "${RED}❌ Alembic не инициализирован!${NC}"
    echo ""
    echo "Для инициализации Alembic выполни:"
    echo "  pip install alembic"
    echo "  alembic init alembic"
    echo ""
    echo "Затем обнови alembic/env.py с конфигурацией SQLAlchemy"
    exit 1
fi

# Активация виртуального окружения
if [ ! -d "venv" ]; then
    echo "❌ Виртуальное окружение не найдено. Запусти run_dev.sh"
    exit 1
fi

source venv/bin/activate

# Проверка .env
if [ ! -f ".env" ]; then
    echo "⚠️  Файл .env не найден!"
    exit 1
fi

# Меню выбора операции
echo ""
echo -e "${BLUE}Выбери операцию:${NC}"
echo "1) Создать новую миграцию (autogenerate)"
echo "2) Применить все ожидающие миграции"
echo "3) Откатить на одну миграцию"
echo "4) Показать статус миграций"
echo ""

read -p "Выбор (1-4): " choice

case $choice in
    1)
        echo -e "${YELLOW}Создание новой миграции...${NC}"
        read -p "Введи описание миграции (или Enter для auto): " migration_desc

        if [ -z "$migration_desc" ]; then
            alembic revision --autogenerate
        else
            alembic revision --autogenerate -m "$migration_desc"
        fi

        echo -e "${GREEN}✅ Миграция создана${NC}"
        echo "   Проверь файл в alembic/versions/"
        ;;
    2)
        echo -e "${YELLOW}Применение миграций...${NC}"
        alembic upgrade head
        echo -e "${GREEN}✅ Миграции применены${NC}"
        ;;
    3)
        echo -e "${YELLOW}Откат на одну миграцию...${NC}"
        alembic downgrade -1
        echo -e "${GREEN}✅ Откат выполнен${NC}"
        ;;
    4)
        echo -e "${BLUE}Статус миграций:${NC}"
        alembic current
        ;;
    *)
        echo -e "${RED}❌ Неверный выбор${NC}"
        exit 1
        ;;
esac

echo ""
echo "-----------------------------------"

# Деактивация виртуального окружения
deactivate
